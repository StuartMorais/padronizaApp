from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtGui import QIcon


WINDOWS_APP_ID = "Padroniza.Desktop"


def configure_windows_app_id() -> None:
    """Give Padroniza its own Windows taskbar identity."""

    if sys.platform != "win32":
        return

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_ID
        )
    except (AttributeError, OSError):
        pass


def load_application_icon(resource_root: Path) -> QIcon:
    """Load the first available Padroniza icon."""

    candidates = (
        resource_root / "assets" / "padroniza.ico",
        resource_root / "assets" / "padroniza.png",
    )

    for icon_path in candidates:
        if not icon_path.is_file():
            continue

        icon = QIcon(str(icon_path))

        if not icon.isNull():
            return icon

    return QIcon()