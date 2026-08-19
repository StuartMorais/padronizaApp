from __future__ import annotations

import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QTimer, QTranslator
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from app.ui.icon import (
    configure_windows_app_id,
    load_application_icon,
)

from app.core.paths import (
    StorageInitializationError,
    initialize_persistent_storage,
    resolve_application_paths,
)
from app.ui.main_window import MainWindow
from app.core.settings import (
    APPLICATION,
    ORGANIZATION,
    configure_settings_storage,
    migrate_legacy_settings,
)
from app.ui.theme import ThemeManager
from app.core.schema import SchemaVersionError, migrate_qsettings
from app.core.application_logging import configure_application_logging, install_exception_logging


def main() -> int:
    paths = resolve_application_paths()

    configure_windows_app_id()

    try:
        initialize_persistent_storage(paths)
    except StorageInitializationError as exc:
        emergency_app = QApplication.instance() or QApplication(sys.argv)

        emergency_icon = load_application_icon(paths.resource_root)
        if not emergency_icon.isNull():
            emergency_app.setWindowIcon(emergency_icon)

        QMessageBox.critical(
            None,
            "Não foi possível iniciar o Padroniza",
            str(exc),
        )
        return 1

    configure_application_logging(paths.storage_root)
    install_exception_logging()
    configure_settings_storage(paths.storage_root)
    migrate_legacy_settings(paths.storage_root)

    QLocale.setDefault(
        QLocale(
            QLocale.Language.Portuguese,
            QLocale.Country.Brazil,
        )
    )

    app = QApplication.instance() or QApplication(sys.argv)

    app_icon = load_application_icon(paths.resource_root)
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    qt_translator = QTranslator(app)
    translations_path = QLibraryInfo.path(
        QLibraryInfo.LibraryPath.TranslationsPath
    )

    for catalog in (
        "qtbase_pt_BR",
        "qt_pt_BR",
        "qtbase_pt",
        "qt_pt",
    ):
        if qt_translator.load(catalog, translations_path):
            app.installTranslator(qt_translator)
            break

    app.setApplicationName(APPLICATION)
    app.setApplicationDisplayName(APPLICATION)
    app.setOrganizationName(ORGANIZATION)
    app.setStyle("Fusion")

    settings = QSettings(ORGANIZATION, APPLICATION)
    try:
        migrate_qsettings(settings)
    except SchemaVersionError as exc:
        QMessageBox.critical(
            None,
            "Dados de uma versão mais nova",
            str(exc) + "\n\nAtualize o Padroniza para abrir esses dados com segurança.",
        )
        return 1
    base_size = int(
        settings.value(
            "accessibility/font_size",
            10,
        )
        or 10
    )

    app.setFont(
        QFont(
            "Segoe UI",
            max(8, min(18, base_size)),
        )
    )

    theme_manager = ThemeManager(
        app=app,
        project_root=paths.resource_root,
    )
    theme_manager.apply_theme(
        theme_manager.current_theme()
    )

    try:
        window = MainWindow(
            project_root=paths.storage_root,
            theme_manager=theme_manager,
            default_output_dir=paths.default_output_root,
            managed_storage=paths.frozen,
        )
    except SchemaVersionError as exc:
        QMessageBox.critical(
            None,
            "Dados de uma versão mais nova",
            str(exc) + "\n\nNenhum dado foi alterado. Atualize o Padroniza para continuar.",
        )
        return 1

    if not app_icon.isNull():
        window.setWindowIcon(app_icon)

    window.show()

    # CI/startup smoke mode exercises the real window construction, theme,
    # storage and template discovery paths without waiting for user input.
    if "--smoke-test" in sys.argv:
        QTimer.singleShot(350, app.quit)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
