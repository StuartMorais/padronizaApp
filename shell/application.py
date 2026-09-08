from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from shell import __version__
from shell.branding import APP_ID, APP_NAME, ORGANIZATION
from shell.icons import icon


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if root.handlers:
        return
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        directory = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / "nexo.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)


def create_application(argv: list[str] | None = None) -> QApplication:
    """Call once, before creating any widget. Adapters must not call this."""
    if QApplication.instance() is not None:
        raise RuntimeError(f"{APP_NAME} already has a QApplication.")
    app = QApplication(argv or [])
    app.setOrganizationName(ORGANIZATION)
    app.setApplicationName(APP_ID)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(icon("grid", "#7C8CFF", 64))
    configure_logging()
    return app
