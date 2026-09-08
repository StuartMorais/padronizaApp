from __future__ import annotations

from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from adapters.contracts import WorkspaceContext, WorkspaceFactory
from adapters.registry import WORKSPACE_FACTORIES
from shell.about_page import AboutPage
from shell.branding import APP_NAME, MODULE_MARK
from shell.catalog import MODULES, PAGE_TITLES
from shell.dashboard import HomeDashboard
from shell.preferences import Preferences
from shell.settings_page import SettingsPage
from shell.sidebar import Sidebar
from shell.theme import stylesheet
from shell.widgets import label
from shell.workspace_host import WorkspaceHost


class OfficeMainWindow(QMainWindow):
    def __init__(self, preferences: Preferences | None = None, factories: dict[str, WorkspaceFactory] | None = None) -> None:
        super().__init__()
        self.setObjectName("OfficeWindow")
        self.preferences = preferences if preferences is not None else Preferences()
        self.current_page = "home"
        self.setMinimumSize(960, 650)
        self.resize(1280, 860)
        self.setStyleSheet(stylesheet(self.preferences.theme))

        root = QWidget()
        root.setObjectName("OfficeShell")
        self.setCentralWidget(root)
        main_layout = QHBoxLayout(root)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        self.sidebar = Sidebar()
        main_layout.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        header = QFrame()
        header.setObjectName("ShellHeader")
        header.setFixedHeight(72)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(32, 0, 32, 0)
        header_layout.addWidget(label("Espaço de trabalho", "caption"))
        header_layout.addWidget(label("/", "caption"))
        self.breadcrumb = label("Início", "breadcrumb")
        header_layout.addWidget(self.breadcrumb)
        header_layout.addStretch(1)
        header_layout.addWidget(label(MODULE_MARK, "headerMark"))
        right_layout.addWidget(header)

        self.pages = QStackedWidget()
        self.pages.setObjectName("ShellPages")
        right_layout.addWidget(self.pages, 1)
        main_layout.addWidget(right, 1)
        self.home_page = HomeDashboard()
        self.settings_page = SettingsPage(self.preferences)
        self.about_page = AboutPage()
        self.page_widgets: dict[str, QWidget] = {"home": self.home_page}
        self.pages.addWidget(self.home_page)
        context = WorkspaceContext(
            return_home=lambda: self.navigate("home"),
            get_theme=lambda: self.preferences.theme,
        )
        registry = WORKSPACE_FACTORIES if factories is None else factories
        self.hosts = {}
        for spec in MODULES:
            host = WorkspaceHost(spec, registry.get(spec.key), context)
            self.hosts[spec.key] = host
            self.page_widgets[spec.key] = host
            self.pages.addWidget(host)
        for key, page in (("settings", self.settings_page), ("about", self.about_page)):
            self.page_widgets[key] = page
            self.pages.addWidget(page)

        self.sidebar.navigate_requested.connect(self.navigate)
        self.home_page.navigate_requested.connect(self.navigate)
        self.settings_page.preferences_saved.connect(self.apply_theme)
        self.shortcuts = []
        for keys, page in (("Ctrl+1", "home"), ("Ctrl+2", "padroniza"), ("Ctrl+3", "checklist"), ("Ctrl+,", "settings"), ("F1", "about")):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.activated.connect(lambda target=page: self.navigate(target))
            self.shortcuts.append(shortcut)

        geometry = self.preferences.geometry
        if self.preferences.remember_window and geometry:
            self.restoreGeometry(geometry)
        else:
            screen = QApplication.primaryScreen()
            if screen:
                available = screen.availableGeometry()
                self.resize(min(1280, available.width()), min(860, available.height()))
                frame = self.frameGeometry()
                frame.moveCenter(available.center())
                self.move(frame.topLeft())
        self.navigate(self.preferences.start_page)

    def navigate(self, page: str) -> bool:
        if page not in self.page_widgets:
            raise ValueError(f"Unknown page: {page}")
        active_host = self.hosts.get(self.current_page)
        if page != self.current_page and active_host and not active_host.allows("can_leave"):
            self.sidebar.set_current(self.current_page)
            return False
        host = self.hosts.get(page)
        if host:
            host.ensure_loaded()
            if host.workspace is not None:
                set_theme = getattr(host.workspace, "set_theme", None)
                if callable(set_theme):
                    set_theme(self.preferences.theme)
        self.pages.setCurrentWidget(self.page_widgets[page])
        self.current_page = page
        self.sidebar.set_current(page)
        self.breadcrumb.setText(PAGE_TITLES[page])
        self.setWindowTitle(f"{APP_NAME} — {PAGE_TITLES[page]}")
        return True


    def apply_theme(self) -> None:
        theme = self.preferences.theme
        self.setStyleSheet(stylesheet(theme))
        for host in self.hosts.values():
            if host.workspace is None:
                continue
            set_theme = getattr(host.workspace, "set_theme", None)
            if callable(set_theme):
                set_theme(theme)

    def closeEvent(self, event: QCloseEvent) -> None:
        # Check all loaded workspaces, including hidden ones with pending work.
        for host in self.hosts.values():
            if not host.allows("can_close"):
                event.ignore()
                return
        self.preferences.save_geometry(self.saveGeometry())
        event.accept()
