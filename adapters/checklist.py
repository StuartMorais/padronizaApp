from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

from adapters.contracts import WorkspaceContext


def create_checklist(context: WorkspaceContext) -> QWidget:
    """Create Checklist inside the existing Nexo QApplication."""
    from checklist_app.main_window import ChecklistMainWindow
    from checklist_app.theme import build_qss
    from adapters.checklist_workspace import ChecklistWorkspaceWrapper

    application = QApplication.instance()
    if application is None:
        raise RuntimeError("Nexo must create QApplication before Checklist.")

    workspace = ChecklistMainWindow()
    theme = context.get_theme()
    workspace.current_theme = theme
    workspace.setStyleSheet(build_qss(theme))
    workspace.refresh_all()
    return ChecklistWorkspaceWrapper(workspace, context)
