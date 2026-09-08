from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from checklist_app.main_window import ChecklistMainWindow
from checklist_app.resources import resource_path
from checklist_app.theme import apply_theme, get_saved_theme


def main() -> int:
    app = QApplication(sys.argv)
    apply_theme(app, get_saved_theme())
    icon_path = resource_path("assets/icon.ico")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = ChecklistMainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
