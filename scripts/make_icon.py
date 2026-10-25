"""Regenerate the app icon (PNG for the window, ICO for the .exe).

    python scripts/make_icon.py
Requires Pillow (pip install pillow).
"""

import io
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QIODevice  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main() -> None:
    QApplication(sys.argv[:1])
    from spacescout.ui.widgets import app_icon_pixmap

    pm = app_icon_pixmap(256)
    png_path = os.path.join(ROOT, "src", "spacescout", "assets", "icon.png")
    os.makedirs(os.path.dirname(png_path), exist_ok=True)
    pm.save(png_path, "PNG")

    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    pm.save(buf, "PNG")
    img = Image.open(io.BytesIO(bytes(buf.data())))
    ico_path = os.path.join(ROOT, "assets", "icon.ico")
    os.makedirs(os.path.dirname(ico_path), exist_ok=True)
    img.save(ico_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote", png_path, "and", ico_path)


if __name__ == "__main__":
    main()
