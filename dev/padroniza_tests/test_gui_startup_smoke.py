from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.theme import ThemeManager


def test_main_window_constructs_and_closes(tmp_path):
    app = QApplication.instance() or QApplication([])
    project_root = Path(__file__).resolve().parents[1]
    for folder in ("templates", "data", "backups", "output"):
        (tmp_path / folder).mkdir(exist_ok=True)

    settings_root = tmp_path / "data" / "qsettings"
    settings_root.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(settings_root),
    )

    theme = ThemeManager(app=app, project_root=project_root)
    theme.apply_theme("light")
    window = MainWindow(
        project_root=tmp_path,
        theme_manager=theme,
        default_output_dir=tmp_path / "output",
    )
    assert "Padroniza" in window.windowTitle()
    window.close()
