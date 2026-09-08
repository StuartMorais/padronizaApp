from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


SETTINGS_ORGANIZATION = "ChecklistPython"
SETTINGS_APPLICATION = "Checklist Application"
VALID_THEMES = {"light", "dark"}


PALETTES = {
    "light": {
        "bg": "#f3f5f7",
        "surface": "#ffffff",
        "surface_alt": "#f8fafc",
        "hero": "#eef6ff",
        "hero_border": "#c9def7",
        "text": "#1f2933",
        "title": "#111827",
        "muted": "#5d6b7a",
        "border": "#cfd8e3",
        "border_strong": "#9aa8b7",
        "input_border": "#b9c4d1",
        "header": "#d9dde3",
        "header_text": "#111827",
        "accent": "#0969da",
        "accent_hover": "#1677e8",
        "accent_soft": "#dbeafe",
        "accent_text": "#0f62b8",
        "danger_bg": "#fff1f2",
        "danger_border": "#fca5a5",
        "danger_text": "#991b1b",
        "disabled_bg": "#f0f2f4",
        "disabled_text": "#9aa6b2",
        "scroll": "#cbd5e1",
    },
    "dark": {
        "bg": "#0b1220",
        "surface": "#111a2b",
        "surface_alt": "#162235",
        "hero": "#13243b",
        "hero_border": "#294668",
        "text": "#e5edf7",
        "title": "#f8fafc",
        "muted": "#9fb0c5",
        "border": "#2a3a4f",
        "border_strong": "#42556d",
        "input_border": "#3a4d65",
        "header": "#243244",
        "header_text": "#f8fafc",
        "accent": "#2f7df4",
        "accent_hover": "#4b91fa",
        "accent_soft": "#17345a",
        "accent_text": "#8cc0ff",
        "danger_bg": "#3b171d",
        "danger_border": "#7f3440",
        "danger_text": "#ffb4bd",
        "disabled_bg": "#172131",
        "disabled_text": "#64748b",
        "scroll": "#405168",
    },
}


QSS_TEMPLATE = r"""
QWidget {
    background-color: @BG@;
    color: @TEXT@;
    font-family: "Segoe UI";
    font-size: 10pt;
}

QMainWindow { background-color: @BG@; }
QLabel { background-color: transparent; border: none; }
QLabel#pageTitle { color: @TITLE@; font-size: 17pt; font-weight: 900; }
QLabel#sectionTitle { color: @TITLE@; font-size: 12pt; font-weight: 900; }
QLabel#mutedText { color: @MUTED@; }
QLabel#metricValue { color: @ACCENT_TEXT@; font-size: 21pt; font-weight: 900; }
QLabel#metricLabel { color: @TEXT@; font-weight: 800; }
QLabel#statusBadge {
    background-color: @SURFACE_ALT@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    border-radius: 9px;
    padding: 4px 9px;
    font-size: 8.8pt;
    font-weight: 800;
}
QLabel#officialTitle { color: @TITLE@; font-size: 11.5pt; font-weight: 900; letter-spacing: 0.2px; }
QLabel#officialSubtitle { color: @TEXT@; font-size: 9.5pt; font-weight: 700; }
QLabel#workspaceBrand { color: @TITLE@; font-size: 11pt; font-weight: 900; padding-right: 8px; }
QLabel#workspaceLabel { color: @MUTED@; font-size: 8.5pt; font-weight: 900; padding: 0 5px 0 8px; }

QFrame#workspaceBar {
    background-color: @SURFACE@;
    border: none;
    border-bottom: 1px solid @BORDER@;
}
QFrame#workspaceSeparator {
    color: @BORDER@;
    background-color: @BORDER@;
    max-width: 1px;
    margin: 5px 3px;
}
QFrame#homeHero,
QFrame#card,
QFrame#panelCard,
QFrame#templateHeader,
QFrame#scannerHero,
QFrame#paperPanel,
QFrame#guidancePanel,
QFrame#officialHeader {
    background-color: @SURFACE@;
    border: 1px solid @BORDER@;
    border-radius: 10px;
}
QFrame#homeHero,
QFrame#scannerHero {
    background-color: @HERO@;
    border-color: @HERO_BORDER@;
}
QFrame#paperPanel {
    background-color: @SURFACE@;
    border-color: @BORDER_STRONG@;
}
QFrame#officialHeader {
    background-color: @SURFACE@;
    border: 1px solid @BORDER_STRONG@;
    border-radius: 4px;
}
QFrame#guidancePanel {
    background-color: @SURFACE_ALT@;
    border-color: @BORDER@;
    border-radius: 8px;
}

QListWidget#libraryList {
    background-color: @SURFACE@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    padding: 6px;
    outline: none;
}
QListWidget#libraryList::item {
    border-radius: 7px;
    padding: 9px 10px;
    margin: 2px 0;
}
QListWidget#libraryList::item:selected {
    background-color: @ACCENT_SOFT@;
    color: @ACCENT_TEXT@;
    border-left: 3px solid @ACCENT@;
}

QLineEdit,
QPlainTextEdit,
QComboBox {
    background-color: @SURFACE@;
    color: @TEXT@;
    border: 1px solid @INPUT_BORDER@;
    border-radius: 6px;
    padding: 7px 9px;
    min-height: 22px;
    selection-background-color: @ACCENT@;
    selection-color: #ffffff;
}
QLineEdit:hover,
QPlainTextEdit:hover,
QComboBox:hover { border-color: @BORDER_STRONG@; }
QLineEdit:focus,
QPlainTextEdit:focus,
QComboBox:focus { border: 1px solid @ACCENT@; }
QLineEdit:disabled,
QPlainTextEdit:disabled,
QComboBox:disabled {
    background-color: @DISABLED_BG@;
    color: @DISABLED_TEXT@;
}

QPushButton {
    background-color: @SURFACE@;
    color: @TEXT@;
    border: 1px solid @INPUT_BORDER@;
    border-radius: 6px;
    padding: 7px 12px;
    min-height: 24px;
    font-weight: 700;
}
QPushButton:hover {
    background-color: @SURFACE_ALT@;
    border-color: @BORDER_STRONG@;
}
QPushButton:pressed { background-color: @ACCENT_SOFT@; }
QPushButton:disabled {
    color: @DISABLED_TEXT@;
    background-color: @DISABLED_BG@;
    border-color: @BORDER@;
}
QPushButton#primaryButton {
    background-color: @ACCENT@;
    border-color: @ACCENT@;
    color: #ffffff;
    font-weight: 900;
    padding-left: 18px;
    padding-right: 18px;
}
QPushButton#primaryButton:hover { background-color: @ACCENT_HOVER@; }
QPushButton#dangerButton {
    background-color: @DANGER_BG@;
    border-color: @DANGER_BORDER@;
    color: @DANGER_TEXT@;
}
QPushButton#dangerButton:hover { border-color: @DANGER_TEXT@; }
QPushButton#workspaceNavButton { padding-left: 14px; padding-right: 14px; }
QPushButton#workspaceNavButton:checked {
    background-color: @ACCENT@;
    border-color: @ACCENT@;
    color: #ffffff;
    font-weight: 900;
}
QPushButton#themeButton { min-width: 92px; }

QMenu {
    background-color: @SURFACE@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    padding: 5px;
}
QMenu::item {
    padding: 7px 28px 7px 10px;
    border-radius: 5px;
}
QMenu::item:selected {
    background-color: @ACCENT_SOFT@;
    color: @ACCENT_TEXT@;
}
QMenu::separator {
    height: 1px;
    background: @BORDER@;
    margin: 5px 8px;
}
QProgressBar {
    background-color: @SURFACE_ALT@;
    border: 1px solid @BORDER@;
    border-radius: 5px;
    min-height: 8px;
    max-height: 8px;
}
QProgressBar::chunk {
    background-color: @ACCENT@;
    border-radius: 4px;
}

QTableWidget#checklistSheetTable {
    background-color: @SURFACE@;
    alternate-background-color: @SURFACE@;
    color: @TEXT@;
    border: 1px solid @BORDER_STRONG@;
    border-radius: 2px;
    gridline-color: @BORDER_STRONG@;
    selection-background-color: @ACCENT_SOFT@;
    selection-color: @TEXT@;
}
QTableWidget#checklistSheetTable::item { padding: 5px; }
QTableWidget#checklistSheetTable::item:selected {
    background-color: @ACCENT_SOFT@;
    color: @TEXT@;
}
QTableWidget#checklistSheetTable QHeaderView::section {
    background-color: @HEADER@;
    color: @HEADER_TEXT@;
    border: none;
    border-right: 1px solid @BORDER_STRONG@;
    border-bottom: 1px solid @BORDER_STRONG@;
    padding: 7px;
    font-size: 8.8pt;
    font-weight: 900;
}
QTableWidget {
    background-color: @SURFACE@;
    alternate-background-color: @SURFACE_ALT@;
    color: @TEXT@;
    border: 1px solid @BORDER@;
    border-radius: 8px;
    gridline-color: @BORDER@;
    selection-background-color: @ACCENT_SOFT@;
    selection-color: @TEXT@;
}
QHeaderView::section {
    background-color: @SURFACE_ALT@;
    color: @TEXT@;
    border: none;
    border-right: 1px solid @BORDER@;
    border-bottom: 1px solid @BORDER@;
    padding: 8px;
    font-weight: 800;
}
QSplitter::handle { background-color: @BORDER@; }
QScrollArea { border: none; background: transparent; }
QStatusBar {
    background-color: @SURFACE@;
    color: @MUTED@;
    border-top: 1px solid @BORDER@;
}
QScrollBar:vertical {
    background: @SURFACE_ALT@;
    width: 11px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: @SCROLL@;
    min-height: 28px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: @SURFACE_ALT@;
    height: 11px;
    margin: 0;
}
QScrollBar::handle:horizontal {
    background: @SCROLL@;
    min-width: 28px;
    border-radius: 5px;
}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal { width: 0; }
"""


def normalize_theme(theme: object) -> str:
    value = str(theme or "").strip().lower()
    return value if value in VALID_THEMES else "light"


def get_saved_theme() -> str:
    settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
    return normalize_theme(settings.value("theme", "light"))


def save_theme(theme: str) -> None:
    settings = QSettings(SETTINGS_ORGANIZATION, SETTINGS_APPLICATION)
    settings.setValue("theme", normalize_theme(theme))


def build_qss(theme: str) -> str:
    palette = PALETTES[normalize_theme(theme)]
    qss = QSS_TEMPLATE

    for key, value in palette.items():
        qss = qss.replace(f"@{key.upper()}@", value)

    return qss


def apply_theme(app: QApplication, theme: str | None = None) -> str:
    selected = normalize_theme(theme or get_saved_theme())
    app.setFont(QFont("Segoe UI", 10))
    app.setStyleSheet(build_qss(selected))
    return selected
