from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication


SETTINGS_ORGANIZATION = "ChecklistPython"
SETTINGS_APPLICATION = "Checklist Application"
VALID_THEMES = {"light", "dark"}


PALETTES = {
    "light": {
        "bg": "#F5F7FB",
        "surface": "#FFFFFF",
        "surface_alt": "#F8FAFC",
        "hero": "#EAF7F5",
        "hero_border": "#A9D9D4",
        "text": "#1E293B",
        "title": "#172033",
        "muted": "#667085",
        "border": "#DFE5EF",
        "border_strong": "#C9D3E1",
        "input_border": "#C9D3E1",
        "header": "#EEF2F7",
        "header_text": "#334155",
        "accent": "#0F8F87",
        "accent_hover": "#0B766F",
        "accent_soft": "#EAF7F5",
        "accent_text": "#0B766F",
        "danger_bg": "#FFF4F5",
        "danger_border": "#E9AAB2",
        "danger_text": "#B23A48",
        "disabled_bg": "#F6F8FB",
        "disabled_text": "#8B98AD",
        "scroll": "#C5D0DE",
    },
    "dark": {
        "bg": "#0F141D",
        "surface": "#161D29",
        "surface_alt": "#1B2432",
        "hero": "#173B39",
        "hero_border": "#356B67",
        "text": "#E7ECF4",
        "title": "#F6F8FC",
        "muted": "#9AA8BC",
        "border": "#2A3545",
        "border_strong": "#39485D",
        "input_border": "#39485D",
        "header": "#202A39",
        "header_text": "#E7ECF4",
        "accent": "#2EC4B6",
        "accent_hover": "#48D3C5",
        "accent_soft": "#173B39",
        "accent_text": "#72D8CF",
        "danger_bg": "#3A2026",
        "danger_border": "#75424A",
        "danger_text": "#FF9AA6",
        "disabled_bg": "#171E29",
        "disabled_text": "#6F7E92",
        "scroll": "#4A586B",
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
