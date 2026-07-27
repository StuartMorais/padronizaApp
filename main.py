from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.runtime_settings import (
    APPLICATION,
    ORGANIZATION,
    configure_settings_storage,
    migrate_legacy_settings,
)
from app.theme_manager import ThemeManager


def main() -> int:
    project_root = Path(__file__).resolve().parent
    configure_settings_storage(project_root)
    migrate_legacy_settings(project_root)

    QLocale.setDefault(
        QLocale(
            QLocale.Language.Portuguese,
            QLocale.Country.Brazil,
        )
    )

    app = QApplication(sys.argv)

    qt_translator = QTranslator(app)
    translations_path = QLibraryInfo.path(
        QLibraryInfo.LibraryPath.TranslationsPath
    )
    for catalog in ("qtbase_pt_BR", "qt_pt_BR", "qtbase_pt", "qt_pt"):
        if qt_translator.load(catalog, translations_path):
            app.installTranslator(qt_translator)
            break

    app.setApplicationName(APPLICATION)
    app.setApplicationDisplayName(APPLICATION)
    app.setOrganizationName(ORGANIZATION)
    app.setStyle("Fusion")

    settings = QSettings(ORGANIZATION, APPLICATION)
    base_size = int(settings.value("accessibility/font_size", 10) or 10)
    app.setFont(QFont("Segoe UI", max(8, min(18, base_size))))

    theme_manager = ThemeManager(
        app=app,
        project_root=project_root,
    )
    theme_manager.apply_theme(
        theme_manager.current_theme()
    )

    window = MainWindow(
        project_root=project_root,
        theme_manager=theme_manager,
    )
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
