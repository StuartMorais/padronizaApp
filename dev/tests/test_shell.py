"""Behavioral checks, using isolated preferences and no original app data."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QBoxLayout, QLineEdit, QMainWindow, QPushButton, QVBoxLayout, QWidget

from shell.application import create_application
from shell.main_window import OfficeMainWindow
from shell.preferences import Preferences


class EditableWorkspace(QWidget):
    def __init__(self):
        super().__init__()
        self.allow_leave = True
        self.allow_close = True
        self.edit = QLineEdit()
        QVBoxLayout(self).addWidget(self.edit)

    def can_leave(self):
        return self.allow_leave

    def can_close(self):
        return self.allow_close


class ShellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_application([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="office-test-")
        self.settings_path = str(Path(self.temp.name) / "prefs.ini")
        self.preferences = Preferences(QSettings(self.settings_path, QSettings.Format.IniFormat))
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            for host in window.hosts.values():
                if isinstance(host.workspace, EditableWorkspace):
                    host.workspace.allow_close = True
            window.close()
            window.deleteLater()
        self.app.processEvents()
        self.temp.cleanup()

    def make_window(self, factories=None):
        window = OfficeMainWindow(self.preferences, factories={} if factories is None else factories)
        self.windows.append(window)
        window.resize(1280, 860)
        window.show()
        self.app.processEvents()
        return window

    def click(self, button):
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.app.processEvents()

    def assert_page(self, window, page):
        self.assertEqual(window.current_page, page)
        self.assertIs(window.pages.currentWidget(), window.page_widgets[page])
        self.assertTrue(window.sidebar.buttons[page].isChecked())
        self.assertEqual(sum(b.isChecked() for b in window.sidebar.buttons.values()), 1)

    def test_cards_sidebar_and_settings_banner_share_navigation(self):
        window = self.make_window()
        self.assert_page(window, "home")
        self.click(window.home_page.cards["padroniza"].open_button)
        self.assert_page(window, "padroniza")
        self.click(window.sidebar.buttons["home"])
        self.click(window.home_page.cards["checklist"].open_button)
        self.assert_page(window, "checklist")
        for page in ("settings", "about", "home"):
            self.click(window.sidebar.buttons[page])
            self.assert_page(window, page)
        self.click(window.home_page.settings_button)
        self.assert_page(window, "settings")

    def test_entire_card_surface_opens_workspace(self):
        window = self.make_window()
        self.click(window.home_page.cards["padroniza"])
        self.assert_page(window, "padroniza")

    def test_keyboard_shortcut_changes_page(self):
        window = self.make_window()
        window.activateWindow()
        window.setFocus()
        QTest.qWait(30)
        QTest.keyClick(window, Qt.Key.Key_3, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assert_page(window, "checklist")
        QTest.keyClick(window, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        self.app.processEvents()
        self.assert_page(window, "home")

    def test_workspace_is_lazy_and_keeps_unsaved_input(self):
        created = []
        def factory(context):
            widget = EditableWorkspace()
            created.append(widget)
            return widget
        window = self.make_window({"padroniza": factory})
        self.assertEqual(created, [])
        window.navigate("padroniza")
        created[0].edit.setText("Rascunho não salvo")
        window.navigate("checklist")
        window.navigate("padroniza")
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0].edit.text(), "Rascunho não salvo")

    def test_can_leave_cancels_navigation_and_restores_sidebar(self):
        window = self.make_window({"padroniza": lambda context: EditableWorkspace()})
        window.navigate("padroniza")
        widget = window.hosts["padroniza"].workspace
        widget.allow_leave = False
        self.click(window.sidebar.buttons["home"])
        self.assert_page(window, "padroniza")
        widget.allow_leave = True
        self.click(window.sidebar.buttons["home"])
        self.assert_page(window, "home")

    def test_hidden_workspace_can_cancel_window_close(self):
        window = self.make_window({"padroniza": lambda context: EditableWorkspace()})
        window.navigate("padroniza")
        widget = window.hosts["padroniza"].workspace
        widget.allow_close = False
        window.navigate("home")
        self.assertFalse(window.close())
        self.assertTrue(window.isVisible())
        widget.allow_close = True
        self.assertTrue(window.close())

    def test_failed_factory_does_not_break_menu_and_can_retry(self):
        attempts = []
        def factory(context):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("Intentional test failure")
            return EditableWorkspace()
        window = self.make_window({"padroniza": factory})
        with self.assertLogs("shell.workspace_host", level="ERROR"):
            window.navigate("padroniza")
        host = window.hosts["padroniza"]
        self.assertTrue(host.failed)
        self.click(window.sidebar.buttons["home"])
        self.assert_page(window, "home")
        window.navigate("padroniza")
        self.click(host.findChild(QPushButton, "retry_padroniza"))
        self.assertFalse(host.failed)
        self.assertIsInstance(host.workspace, EditableWorkspace)
        self.assertEqual(len(attempts), 2)

    def test_qmainwindow_factory_is_rejected(self):
        window = self.make_window({"padroniza": lambda context: QMainWindow()})
        with self.assertLogs("shell.workspace_host", level="ERROR"):
            window.navigate("padroniza")
        self.assertTrue(window.hosts["padroniza"].failed)
        self.assertIsNone(window.hosts["padroniza"].workspace)
        self.assertTrue(window.navigate("home"))

    def test_preferences_save_through_ui_and_apply_on_restart(self):
        window = self.make_window()
        window.navigate("settings")
        settings = window.settings_page
        settings.start_combo.setCurrentIndex(settings.start_combo.findData("checklist"))
        settings.remember_check.setChecked(False)
        self.click(settings.save_button)
        self.assertEqual(settings.status_label.text(), "Preferências salvas.")
        window.close()
        loaded = Preferences(QSettings(self.settings_path, QSettings.Format.IniFormat))
        self.assertEqual(loaded.start_page, "checklist")
        self.assertFalse(loaded.remember_window)
        self.assertIsNone(loaded.geometry)
        next_window = OfficeMainWindow(loaded, factories={})
        self.windows.append(next_window)
        self.assert_page(next_window, "checklist")

    def test_remembered_geometry_round_trip(self):
        window = self.make_window()
        # Qt clamps restored geometry to the current screen. The offscreen
        # screen can be only 800 px wide, smaller than the shell's minimum.
        available = self.app.primaryScreen().availableGeometry()
        width = max(window.minimumWidth(), min(1100, available.width() - 20))
        height = max(window.minimumHeight(), min(740, available.height() - 40))
        window.resize(width, height)
        self.app.processEvents()
        window.close()
        self.assertTrue(self.preferences.geometry)
        next_window = OfficeMainWindow(self.preferences, factories={})
        self.windows.append(next_window)
        self.assertEqual(next_window.width(), width)
        self.assertEqual(next_window.height(), height)

    def test_narrow_layout_stacks_cards_without_horizontal_scroll(self):
        window = self.make_window()
        window.resize(960, 650)
        self.app.processEvents()
        self.assertEqual(window.home_page.cards_layout.direction(), QBoxLayout.Direction.TopToBottom)
        self.assertEqual(window.home_page.horizontalScrollBar().maximum(), 0)
        self.assertGreater(window.home_page.verticalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()
