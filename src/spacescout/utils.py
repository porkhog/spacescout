"""Small formatting and platform helpers."""

from __future__ import annotations

import os
import subprocess
import sys
import time

IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def format_size(num: float, precision: int = 1) -> str:
    """Human readable size using 1024-based units, like Windows Explorer."""
    if num is None:
        return ""
    num = float(num)
    sign = "-" if num < 0 else ""
    num = abs(num)
    for unit in _UNITS:
        if num < 1024 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{sign}{int(num)} B"
            if num >= 100:
                return f"{sign}{num:.0f} {unit}"
            return f"{sign}{num:.{precision}f} {unit}"
        num /= 1024
    return f"{sign}{num:.1f} PB"  # pragma: no cover


def format_count(num: int) -> str:
    return f"{num:,}"


def format_date(ts: float) -> str:
    if not ts:
        return ""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except (OverflowError, OSError, ValueError):
        return ""


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def percent(part: float, whole: float) -> float:
    return (part / whole * 100.0) if whole else 0.0


def long_path(path: str) -> str:
    """Prefix very long Windows paths so file APIs accept them."""
    if IS_WINDOWS and len(path) >= 240 and not path.startswith("\\\\?\\"):
        path = os.path.abspath(path)
        if path.startswith("\\\\"):
            return "\\\\?\\UNC\\" + path[2:]
        return "\\\\?\\" + path
    return path


def reveal_in_file_manager(path: str) -> None:
    """Open the system file manager with the item selected."""
    try:
        if IS_WINDOWS:
            if os.path.isdir(path):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif IS_MAC:
            subprocess.Popen(["open", "-R", path])
        else:
            target = path if os.path.isdir(path) else os.path.dirname(path)
            subprocess.Popen(["xdg-open", target])
    except OSError:
        pass


def open_with_default_app(path: str) -> None:
    try:
        if IS_WINDOWS:
            os.startfile(path)  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError:
        pass


def is_admin() -> bool:
    if IS_WINDOWS:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:
        return False


def restart_as_admin() -> bool:
    """Relaunch the app elevated (Windows UAC prompt). Returns True if launched."""
    if not IS_WINDOWS:
        return False
    import ctypes

    exe = sys.executable
    cwd = os.getcwd()
    if getattr(sys, "frozen", False):  # the packaged SpaceScout.exe
        args = sys.argv[1:]
    elif os.path.basename(sys.argv[0]) == "__main__.py":  # started with  python -m spacescout
        args = ["-m", "spacescout", *sys.argv[1:]]
        cwd = os.path.dirname(os.path.dirname(os.path.abspath(sys.argv[0])))
    else:  # started with  python run.py
        args = [os.path.abspath(sys.argv[0]), *sys.argv[1:]]
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, subprocess.list2cmdline(args), cwd, 1)
    return rc > 32
