from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

from adapters.contracts import WorkspaceContext


def create_checklist(context: WorkspaceContext) -> QWidget:
    """Create Checklist inside the existing Office Tools QApplication."""
    from checklist_app.main_window import ChecklistMainWindow
    from checklist_app.theme import build_qss
    from adapters.checklist_workspace import ChecklistWorkspaceWrapper

    application = QApplication.instance()
    if application is None:
        raise RuntimeError("Office Tools must create QApplication before Checklist.")

    workspace = ChecklistMainWindow()
    # Embedded modules use the Office Tools light palette. Force the Checklist
    # presentation state to light as well so saved standalone dark-mode state
    # cannot leak into explicit table-cell colors or scanner accents.
    workspace.current_theme = "light"
    workspace.setStyleSheet(build_qss("light"))
    workspace.refresh_all()
    return ChecklistWorkspaceWrapper(workspace, context)
