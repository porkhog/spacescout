# PyInstaller build recipe:  pyinstaller SpaceScout.spec --noconfirm --clean
# Produces a single dist/SpaceScout.exe on Windows.
# -*- mode: python ; coding: utf-8 -*-

import sys

a = Analysis(
    ["run.py"],
    pathex=["src"],
    datas=[("src/spacescout/assets", "spacescout/assets")],
    hiddenimports=[],
    excludes=[
        "tkinter",
        "unittest",
        "pytest",
        "PySide6.QtNetwork",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtWebEngineCore",
        "PySide6.QtMultimedia",
        "PySide6.Qt3DCore",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SpaceScout",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico" if sys.platform == "win32" else None,
)
