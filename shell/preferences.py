from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

from shell.branding import APP_ID, ORGANIZATION
from shell.theme import normalize_theme

START_PAGES = ("home", "padroniza", "checklist")


class Preferences:
    """Preferences owned by the Nexo shell; module data stays with each module."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self.settings = settings if settings is not None else QSettings(ORGANIZATION, APP_ID)

    @property
    def start_page(self) -> str:
        page = str(self.settings.value("navigation/start_page", "home"))
        return page if page in START_PAGES else "home"

    @property
    def remember_window(self) -> bool:
        return self.settings.value("window/remember", True, type=bool)

    @property
    def theme(self) -> str:
        return normalize_theme(str(self.settings.value("appearance/theme", "light")))

    @property
    def geometry(self) -> QByteArray | None:
        value = self.settings.value("window/geometry")
        return value if isinstance(value, QByteArray) else None

    def save(self, start_page: str, remember_window: bool, theme: str) -> bool:
        if start_page not in START_PAGES:
            raise ValueError(f"Unknown start page: {start_page}")
        selected_theme = normalize_theme(theme)
        self.settings.setValue("navigation/start_page", start_page)
        self.settings.setValue("window/remember", remember_window)
        self.settings.setValue("appearance/theme", selected_theme)
        if not remember_window:
            self.settings.remove("window/geometry")
        self.settings.sync()
        return self.settings.status() == QSettings.Status.NoError

    def save_geometry(self, geometry: QByteArray) -> None:
        if self.remember_window:
            self.settings.setValue("window/geometry", geometry)
        else:
            self.settings.remove("window/geometry")
        self.settings.sync()
