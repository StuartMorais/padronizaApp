from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QWidget

from adapters.contracts import WorkspaceContext


def create_padroniza(context: WorkspaceContext) -> QWidget:
    """Create Padroniza inside the existing Nexo QApplication.

    Startup work that belongs to Padroniza (persistent storage, settings schema,
    logging and template discovery roots) is preserved, while application-wide
    identity, icon, event loop and styling remain owned by Nexo.
    """
    from app.core.application_logging import configure_application_logging
    from app.core.paths import initialize_persistent_storage, resolve_application_paths
    from app.core.schema import migrate_qsettings
    from app.core.settings import (
        APPLICATION,
        ORGANIZATION,
        configure_settings_storage,
        migrate_legacy_settings,
    )
    from app.ui.main_window import MainWindow
    from app.ui.theme import ThemeManager
    from adapters.padroniza_workspace import PadronizaWorkspaceWrapper

    application = QApplication.instance()
    if application is None:
        raise RuntimeError("Nexo must create QApplication before Padroniza.")

    paths = resolve_application_paths()
    initialize_persistent_storage(paths)
    configure_application_logging(paths.storage_root)
    configure_settings_storage(paths.storage_root)
    migrate_legacy_settings(paths.storage_root)

    settings = QSettings(ORGANIZATION, APPLICATION)
    migrate_qsettings(settings)

    theme_manager = ThemeManager(
        app=application,
        project_root=paths.resource_root,
    )
    workspace = MainWindow(
        project_root=paths.storage_root,
        theme_manager=theme_manager,
        default_output_dir=paths.default_output_root,
        managed_storage=paths.frozen,
        embedded=True,
        return_home=context.return_home,
    )
    return PadronizaWorkspaceWrapper(workspace, context.get_theme())
