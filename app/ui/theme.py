from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.core.settings import APPLICATION, ORGANIZATION


class ThemeManager:
    LIGHT = "light"
    DARK = "dark"

    def __init__(
        self,
        app: QApplication,
        project_root: Path,
    ) -> None:
        self.app = app
        self.project_root = Path(project_root)
        self.settings = QSettings(
            ORGANIZATION,
            APPLICATION,
        )

    def current_theme(self) -> str:
        value = str(
            self.settings.value(
                "appearance/theme",
                self.LIGHT,
            )
        ).strip().lower()

        if value not in {
            self.LIGHT,
            self.DARK,
        }:
            return self.LIGHT

        return value

    def apply_theme(
        self,
        theme: str,
    ) -> None:
        theme = str(theme).strip().lower()

        if theme not in {
            self.LIGHT,
            self.DARK,
        }:
            theme = self.LIGHT

        stylesheet_path = (
            self.project_root
            / "app"
            / "ui"
            / "styles"
            / f"{theme}.qss"
        )

        stylesheet = ""

        if stylesheet_path.exists():
            stylesheet = stylesheet_path.read_text(
                encoding="utf-8"
            )

        if bool(self.settings.value("accessibility/high_contrast", False, type=bool)):
            stylesheet += """
QWidget { color: #ffffff; background-color: #000000; }
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QTableWidget, QListWidget {
    color: #ffffff; background-color: #000000; border: 2px solid #ffffff;
}
QPushButton { color: #ffffff; background-color: #111111; border: 2px solid #ffffff; }
QPushButton:hover, QPushButton:focus { background-color: #ffffff; color: #000000; }
QTableWidget::item:selected, QListWidget::item:selected { background-color: #ffffff; color: #000000; }
"""

        font_size = int(self.settings.value("accessibility/font_size", 10) or 10)
        self.app.setFont(QFont("Segoe UI", max(8, min(18, font_size))))
        self.app.setStyleSheet(stylesheet)
        self.settings.setValue(
            "appearance/theme",
            theme,
        )
        self.settings.sync()

    def toggle_theme(self) -> str:
        next_theme = (
            self.DARK
            if self.current_theme() == self.LIGHT
            else self.LIGHT
        )

        self.apply_theme(next_theme)
        return next_theme
