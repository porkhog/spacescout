"""Guard rails: which paths are too dangerous to delete or move.

CRITICAL  - never allowed, in any mode (drive roots, core Windows folders,
            user profile folders, pagefile...).
CAUTION   - blocked in Simple mode; allowed in Advanced mode after an extra
            warning (installed programs, the rest of the Windows folder,
            AppData...).
OK        - normal files and folders.
"""

from __future__ import annotations

import ntpath
import os
import posixpath
import sys
from dataclasses import dataclass
from enum import IntEnum


class Level(IntEnum):
    OK = 0
    CAUTION = 1
    CRITICAL = 2


@dataclass(frozen=True)
class Protection:
    level: Level
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.level == Level.OK


OK = Protection(Level.OK)

_WIN_ROOT_SYSTEM_FILES = {
    "pagefile.sys": "This is Windows' virtual memory file. Change its size in System settings instead.",
    "hiberfil.sys": "This is the hibernation file. Turn off hibernation (powercfg /h off) if you never use it.",
    "swapfile.sys": "Windows manages this file itself.",
    "dumpstack.log.tmp": "Windows manages this file itself.",
    "bootmgr": "Your PC needs this file to start.",
    "bootnxt": "Your PC needs this file to start.",
}
_APPS_REASON = "Installed programs live here. Uninstall them from Settings > Apps instead."
_WIN_SYSTEM_CRITICAL = {"system32", "syswow64", "winsxs", "boot", "fonts", "servicing", "systemapps", "inf"}


def classify(path: str, *, windows: bool | None = None, env: dict | None = None) -> Protection:
    """Return how risky it is to delete or move `path`."""
    if windows is None:
        windows = sys.platform == "win32"
    env = os.environ if env is None else env
    return _classify_windows(path, env) if windows else _classify_posix(path, env)


def _classify_windows(path: str, env) -> Protection:
    p = ntpath
    full = p.normcase(p.normpath(path))
    drive, rest = p.splitdrive(full)
    rest = rest.strip("\\")
    if not rest:
        return Protection(Level.CRITICAL, "You can't delete or move a whole drive.")
    parts = rest.split("\\")
    top, depth = parts[0], len(parts)

    sysroot = p.normcase(p.normpath(env.get("SystemRoot") or env.get("windir") or r"C:\Windows"))
    sys_drive = p.splitdrive(sysroot)[0]
    on_sys = drive == sys_drive

    # --- rules for every drive -------------------------------------------
    if depth == 1 and top in _WIN_ROOT_SYSTEM_FILES:
        return Protection(Level.CRITICAL, _WIN_ROOT_SYSTEM_FILES[top])
    if top == "$recycle.bin":
        return Protection(Level.CRITICAL, "This is the Recycle Bin. Use 'Empty Recycle Bin' instead.")
    if top == "system volume information":
        return Protection(Level.CRITICAL, "Windows keeps restore points here. Manage them in System Protection.")
    if top in ("windowsapps", "program files", "program files (x86)") and not on_sys:
        return Protection(Level.CAUTION, _APPS_REASON)

    if not on_sys:
        return OK

    # --- rules for the Windows drive ------------------------------------
    if top in ("boot", "efi", "recovery"):
        return Protection(Level.CRITICAL, "Your PC needs this to start or repair itself.")

    if full == sysroot or full.startswith(sysroot + "\\"):
        sub = full[len(sysroot):].strip("\\").split("\\") if full != sysroot else []
        if not sub or sub[0] in _WIN_SYSTEM_CRITICAL:
            return Protection(Level.CRITICAL, "Windows needs this to run.")
        if sub[0] == "temp" and len(sub) > 1:
            return OK
        return Protection(Level.CAUTION, "This is part of Windows. Removing it can break your PC.")

    profile = env.get("USERPROFILE")
    users_dir = p.normcase(p.dirname(p.normpath(profile))) if profile else sys_drive + "\\users"
    if full == users_dir:
        return Protection(Level.CRITICAL, "This holds every account on the PC.")
    if full.startswith(users_dir + "\\"):
        sub = full[len(users_dir):].strip("\\").split("\\")
        if len(sub) == 1:
            return Protection(Level.CRITICAL, "This is a whole user account folder.")
        if len(sub) == 2 and (sub[1] == "appdata" or sub[1].startswith("ntuser")):
            return Protection(Level.CRITICAL, "Windows keeps this account's settings here.")
        if sub[1] == "appdata":
            if len(sub) >= 4 and sub[2] == "local" and sub[3] == "temp":
                return OK  # temp files are fair game
            return Protection(Level.CAUTION, "Apps keep their settings and data here.")
        return OK

    if top in ("program files", "program files (x86)", "programdata"):
        if depth == 1:
            return Protection(Level.CRITICAL, "Every installed program depends on this folder.")
        return Protection(Level.CAUTION, _APPS_REASON if top != "programdata" else "Programs keep shared settings and data here.")
    return OK


_POSIX_CRITICAL = {
    "/", "/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/libx32", "/proc", "/root",
    "/run", "/sbin", "/sys", "/usr", "/var", "/home", "/opt", "/srv", "/snap",
    "/system", "/library", "/applications", "/users", "/private", "/volumes", "/cores",
}
_POSIX_CAUTION_PREFIX = ("/usr/", "/etc/", "/var/", "/opt/", "/system/", "/library/", "/applications/", "/bin/", "/sbin/", "/lib", "/boot/", "/snap/")


def _classify_posix(path: str, env) -> Protection:
    p = posixpath
    full = p.normpath(path)
    low = full.lower()
    if low in _POSIX_CRITICAL:
        return Protection(Level.CRITICAL, "Your system needs this folder.")
    home = env.get("HOME")
    if home and p.normpath(home) == full:
        return Protection(Level.CRITICAL, "This is your whole home folder.")
    if low.startswith(_POSIX_CAUTION_PREFIX):
        return Protection(Level.CAUTION, "This is a system or application folder.")
    if home and full.startswith(p.normpath(home) + "/"):
        rel = full[len(p.normpath(home)) + 1:]
        if rel in (".config", ".local", "Library", ".ssh"):
            return Protection(Level.CAUTION, "Apps keep their settings here.")
    return OK


def worst(paths, **kw) -> Protection:
    result = OK
    for path in paths:
        pr = classify(path, **kw)
        if pr.level > result.level:
            result = pr
            if pr.level == Level.CRITICAL:
                break
    return result
