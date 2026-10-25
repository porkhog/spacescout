"""Colours and the Qt stylesheet for light and dark themes."""

from __future__ import annotations

import sys

DARK = {
    "name": "dark",
    "bg": "#111318",
    "surface": "#181b22",
    "surface2": "#20242d",
    "hover": "#272c37",
    "border": "#2b303b",
    "text": "#e9ebf0",
    "muted": "#9aa1b0",
    "faint": "#6a7180",
    "accent": "#5b8cff",
    "accent_hover": "#7aa2ff",
    "accent_soft": "rgba(91,140,255,0.16)",
    "accent_text": "#ffffff",
    "danger": "#f2555a",
    "danger_soft": "rgba(242,85,90,0.14)",
    "warning": "#f0a830",
    "success": "#3ecf8e",
    "track": "#2a2f3a",
    "treemap_bg": "#0c0e12",
}

LIGHT = {
    "name": "light",
    "bg": "#f3f4f7",
    "surface": "#ffffff",
    "surface2": "#f2f4f8",
    "hover": "#e9ecf2",
    "border": "#dde1e8",
    "text": "#1a1d24",
    "muted": "#5b6372",
    "faint": "#8a909c",
    "accent": "#3a6df0",
    "accent_hover": "#2f5fd9",
    "accent_soft": "rgba(58,109,240,0.12)",
    "accent_text": "#ffffff",
    "danger": "#d63a40",
    "danger_soft": "rgba(214,58,64,0.10)",
    "warning": "#c4820e",
    "success": "#1e9b62",
    "track": "#e4e7ed",
    "treemap_bg": "#d9dde5",
}

_current = DARK


def current() -> dict:
    return _current


def set_theme(name: str) -> dict:
    global _current
    _current = LIGHT if name == "light" else DARK
    return _current


def font_family() -> str:
    if sys.platform == "win32":
        return '"Segoe UI Variable Text", "Segoe UI", sans-serif'
    if sys.platform == "darwin":
        return '"SF Pro Text", "Helvetica Neue", sans-serif'
    return '"Inter", "Noto Sans", "DejaVu Sans", sans-serif'


def stylesheet(p: dict | None = None) -> str:
    p = p or _current
    return f"""
* {{
    font-family: {font_family()};
    font-size: 10pt;
    color: {p['text']};
    outline: none;
}}
QMainWindow, QWidget#page, QScrollArea, QScrollArea > QWidget > QWidget#scrollBody {{
    background: {p['bg']};
}}
QWidget {{ background: transparent; }}
QMainWindow {{ background: {p['bg']}; }}
QDialog {{ background: {p['surface']}; }}

QLabel[role="h1"] {{ font-size: 20pt; font-weight: 650; }}
QLabel[role="h2"] {{ font-size: 13.5pt; font-weight: 600; }}
QLabel[role="h3"] {{ font-size: 11pt; font-weight: 600; }}
QLabel[role="big"] {{ font-size: 24pt; font-weight: 650; }}
QLabel[role="muted"] {{ color: {p['muted']}; }}
QLabel[role="faint"] {{ color: {p['faint']}; font-size: 9pt; }}
QLabel[role="danger"] {{ color: {p['danger']}; }}
QLabel[role="warning"] {{ color: {p['warning']}; }}
QLabel[role="pill"] {{
    color: {p['muted']}; background: {p['surface2']}; border: 1px solid {p['border']};
    border-radius: 9px; padding: 1px 8px; font-size: 8.5pt;
}}
QLabel[role="lock"] {{
    color: {p['warning']}; font-size: 8.5pt; font-weight: 600;
}}

QFrame#card {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 14px;
}}
QFrame#card[hoverable="true"]:hover {{ border-color: {p['accent']}; }}
QFrame#header {{
    background: {p['surface']};
    border-bottom: 1px solid {p['border']};
}}
QWidget#row {{ background: transparent; border-radius: 9px; }}
QWidget#row:hover {{ background: {p['hover']}; }}
QWidget#toolbar {{ background: {p['surface']}; border-bottom: 1px solid {p['border']}; }}
QWidget#statusline {{ background: {p['surface']}; border-top: 1px solid {p['border']}; }}
QFrame#divider {{ background: {p['border']}; max-height: 1px; min-height: 1px; }}
QFrame#banner {{
    background: {p['accent_soft']}; border-radius: 10px;
}}

QPushButton {{
    background: {p['surface2']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 500;
}}
QPushButton:hover {{ background: {p['hover']}; }}
QPushButton:pressed {{ background: {p['border']}; }}
QPushButton:disabled {{ color: {p['faint']}; background: {p['surface2']}; border-color: {p['border']}; }}
QPushButton[kind="primary"] {{
    background: {p['accent']}; border: 1px solid {p['accent']}; color: {p['accent_text']}; font-weight: 600;
}}
QPushButton[kind="primary"]:hover {{ background: {p['accent_hover']}; border-color: {p['accent_hover']}; }}
QPushButton[kind="primary"]:disabled {{ background: {p['track']}; border-color: {p['track']}; color: {p['faint']}; }}
QPushButton[kind="danger"] {{
    background: {p['danger_soft']}; border: 1px solid transparent; color: {p['danger']}; font-weight: 600;
}}
QPushButton[kind="danger"]:hover {{ background: {p['danger']}; color: #ffffff; }}
QPushButton[kind="danger"]:disabled {{ background: transparent; color: {p['faint']}; }}
QPushButton[kind="ghost"] {{
    background: transparent; border: 1px solid transparent; color: {p['muted']};
}}
QPushButton[kind="ghost"]:hover {{ background: {p['hover']}; color: {p['text']}; }}
QPushButton[kind="link"] {{
    background: transparent; border: none; color: {p['accent']}; padding: 2px 4px;
}}
QPushButton[kind="link"]:hover {{ text-decoration: underline; }}
QPushButton[kind="crumb"] {{
    background: transparent; border: none; color: {p['muted']}; padding: 3px 6px; border-radius: 6px;
}}
QPushButton[kind="crumb"]:hover {{ background: {p['hover']}; color: {p['text']}; }}
QPushButton[kind="crumbCurrent"] {{
    background: transparent; border: none; color: {p['text']}; padding: 3px 6px; font-weight: 600;
}}
QPushButton[kind="chip"] {{
    background: transparent; border: 1px solid {p['border']}; border-radius: 10px; padding: 3px 11px;
    color: {p['muted']}; font-size: 9pt;
}}
QPushButton[kind="chip"]:hover {{ color: {p['text']}; border-color: {p['faint']}; }}
QPushButton[kind="chip"]:checked {{ background: {p['accent_soft']}; border-color: {p['accent']}; color: {p['text']}; }}
QPushButton[kind="small"] {{ padding: 3px 10px; font-size: 9pt; border-radius: 7px; }}
QPushButton[kind="smallDanger"] {{
    padding: 3px 10px; font-size: 9pt; border-radius: 7px;
    background: transparent; border: 1px solid {p['border']}; color: {p['danger']};
}}
QPushButton[kind="smallDanger"]:hover {{ background: {p['danger']}; border-color: {p['danger']}; color: #fff; }}

QWidget#segmented {{
    background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 10px;
}}
QPushButton#segment {{
    background: transparent; border: none; border-radius: 7px; padding: 5px 16px; color: {p['muted']};
    font-weight: 600;
}}
QPushButton#segment:hover {{ color: {p['text']}; }}
QPushButton#segment:checked {{ background: {p['accent']}; color: {p['accent_text']}; }}

QLineEdit {{
    background: {p['surface2']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px 10px;
    selection-background-color: {p['accent']};
}}
QLineEdit:focus {{ border-color: {p['accent']}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 4px; border: 1px solid {p['faint']}; background: {p['surface2']};
}}
QCheckBox::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}
QCheckBox:disabled {{ color: {p['faint']}; }}

QRadioButton {{ spacing: 8px; }}
QRadioButton::indicator {{
    width: 16px; height: 16px; border-radius: 9px; border: 1px solid {p['faint']}; background: {p['surface2']};
}}
QRadioButton::indicator:checked {{ width: 8px; height: 8px; border: 5px solid {p['accent']}; background: {p['accent_text']}; }}
QRadioButton::indicator:disabled {{ border-color: {p['border']}; background: {p['track']}; }}
QRadioButton:disabled {{ color: {p['faint']}; }}

QProgressBar {{
    background: {p['track']}; border: none; border-radius: 5px; min-height: 10px; max-height: 10px;
    text-align: center; color: transparent;
}}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: 5px; }}

QTreeView, QTableView, QListWidget {{
    background: {p['surface']};
    alternate-background-color: {p['surface2']};
    border: none;
    selection-background-color: {p['accent_soft']};
    selection-color: {p['text']};
    gridline-color: transparent;
}}
QTreeView::item, QTableView::item {{ padding: 3px 2px; border: none; }}
QTreeView::item:hover, QTableView::item:hover {{ background: {p['hover']}; }}
QTreeView::item:selected, QTableView::item:selected {{ background: {p['accent_soft']}; color: {p['text']}; }}
QHeaderView {{ background: {p['surface']}; border: none; }}
QHeaderView::section {{
    background: {p['surface']}; color: {p['muted']}; border: none; border-bottom: 1px solid {p['border']};
    padding: 6px 8px; font-weight: 600; font-size: 9pt;
}}
QHeaderView::section:hover {{ color: {p['text']}; }}
QTableCornerButton::section {{ background: {p['surface']}; border: none; }}

QTabWidget::pane {{ border: none; background: {p['surface']}; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {p['muted']}; padding: 8px 14px; border: none;
    border-bottom: 2px solid transparent; font-weight: 600;
}}
QTabBar::tab:hover {{ color: {p['text']}; }}
QTabBar::tab:selected {{ color: {p['text']}; border-bottom: 2px solid {p['accent']}; }}

QSplitter::handle {{ background: {p['border']}; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:horizontal {{ width: 1px; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['border']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p['faint']}; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['border']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::handle:horizontal:hover {{ background: {p['faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMenu {{
    background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 5px;
}}
QMenu::item {{ padding: 6px 22px 6px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p['hover']}; }}
QMenu::item:disabled {{ color: {p['faint']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 4px 6px; }}

QToolTip {{
    background: {p['surface2']}; color: {p['text']}; border: 1px solid {p['border']};
    border-radius: 6px; padding: 5px 8px;
}}
QMessageBox QLabel {{ min-width: 320px; }}
"""
