"""Group files into friendly categories (Videos, Pictures, ...) for Simple mode
and for colouring the treemap."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Category:
    key: str
    label: str
    color: str


CATEGORIES: dict[str, Category] = {
    c.key: c
    for c in (
        Category("videos", "Videos", "#f76b15"),
        Category("pictures", "Pictures", "#e93d82"),
        Category("music", "Music & audio", "#8e4ec6"),
        Category("documents", "Documents", "#3e63dd"),
        Category("archives", "Archives & installers", "#e2a336"),
        Category("apps", "Apps & games", "#30a46c"),
        Category("system", "Windows & system", "#5b6b8c"),
        Category("recycle", "Recycle Bin", "#b8574e"),
        Category("other", "Other files", "#8b93a5"),
    )
}

# Shown in Simple mode for space the scan couldn't see (protected system files etc.)
HIDDEN = Category("hidden", "Hidden & protected", "#3a4150")

_EXT_MAP: dict[str, str] = {}


def _register(key: str, exts: str) -> None:
    for e in exts.split():
        _EXT_MAP["." + e] = key


_register("videos", "mp4 mkv avi mov wmv flv webm m4v mpg mpeg ts m2ts mts 3gp vob ogv")
_register(
    "pictures",
    "jpg jpeg png gif bmp tif tiff webp heic heif raw cr2 cr3 nef arw dng orf rw2 psd "
    "xcf svg ico avif jxl",
)
_register("music", "mp3 wav flac aac ogg oga m4a wma opus aiff aif mid midi alac ape")
_register(
    "documents",
    "pdf doc docx xls xlsx xlsm ppt pptx txt rtf odt ods odp csv md epub mobi pages "
    "numbers key one pst ost",
)
_register(
    "archives",
    "zip rar 7z tar gz tgz bz2 xz zst lz lzma cab iso img dmg msi msix msixbundle "
    "appx appxbundle wim esd vhd vhdx vmdk",
)
_register(
    "apps",
    "exe dll sys ocx pak vpk uasset uexp ucas utoc bsa ba2 wad forge bundle assets "
    "resource rpf big apk obb so dylib jar",
)

# Folder names whose whole contents count as a category, whatever the extension.
_FOLDER_OVERRIDES = {
    "program files": "apps",
    "program files (x86)": "apps",
    "windowsapps": "apps",
    "steamapps": "apps",
    "steamlibrary": "apps",
    "epic games": "apps",
    "xboxgames": "apps",
    "riot games": "apps",
    "gog games": "apps",
    "ea games": "apps",
    "battle.net": "apps",
}
# Only applies to folders directly under a drive root.
_ROOT_FOLDER_OVERRIDES = {
    "windows": "system",
    "system volume information": "system",
    "recovery": "system",
    "$windows.~bt": "system",
    "$windows.~ws": "system",
    "windows.old": "system",
    "$recycle.bin": "recycle",
}
_ROOT_SYSTEM_FILES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log.tmp"}


def category_for_ext(ext: str) -> str:
    return _EXT_MAP.get(ext, "other")


def folder_override(name: str, is_drive_root_child: bool) -> str | None:
    low = name.lower()
    if is_drive_root_child and low in _ROOT_FOLDER_OVERRIDES:
        return _ROOT_FOLDER_OVERRIDES[low]
    return _FOLDER_OVERRIDES.get(low)


def root_file_override(name: str) -> str | None:
    return "system" if name.lower() in _ROOT_SYSTEM_FILES else None


def get(key: str) -> Category:
    if key == HIDDEN.key:
        return HIDDEN
    return CATEGORIES.get(key, CATEGORIES["other"])
