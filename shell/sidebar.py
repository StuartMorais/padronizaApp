from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from shell import __version__
from shell.branding import APP_NAME, MODULE_MARK, TAGLINE
from shell.catalog import MODULES
from shell.icons import icon
from shell.widgets import label

EXPANDED_WIDTH = 224
COMPACT_WIDTH = 76


class Sidebar(QFrame):
    navigate_requested = Signal(str)
    toggle_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self._compact = False
        self.setProperty("compact", False)
        self.setFixedWidth(EXPANDED_WIDTH)
        self.buttons: dict[str, QPushButton] = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.sidebar_layout = QVBoxLayout(self)
        self.sidebar_layout.setContentsMargins(18, 26, 18, 20)
        self.sidebar_layout.setSpacing(8)

        self.brand = QWidget()
        brand_row = QHBoxLayout(self.brand)
        brand_row.setContentsMargins(8, 0, 0, 0)
        brand_row.setSpacing(12)
        self.brand_button = QPushButton()
        self.brand_button.setObjectName("SidebarBrandButton")
        self.brand_button.setFixedSize(32, 32)
        self.brand_button.setIcon(icon("grid", "#92B2FF", 30))
        self.brand_button.setIconSize(QSize(30, 30))
        self.brand_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.brand_button.setAccessibleName("Alternar menu lateral")
        self.brand_button.clicked.connect(self.toggle_requested.emit)
        brand_row.addWidget(self.brand_button)
        self.brand_words = QWidget()
        brand_words = QVBoxLayout(self.brand_words)
        brand_words.setContentsMargins(0, 0, 0, 0)
        brand_words.setSpacing(2)
        brand_words.addWidget(label(APP_NAME, "brand"))
        brand_words.addWidget(label(TAGLINE, "brandSubtitle"))
        brand_row.addWidget(self.brand_words)
        self.sidebar_layout.addWidget(self.brand)
        self.sidebar_layout.addSpacing(38)
        self.workspace_caption = label("  ESPAÇO DE TRABALHO", "navCaption")
        self.sidebar_layout.addWidget(self.workspace_caption)
        self.sidebar_layout.addSpacing(4)
        self.sidebar_layout.addWidget(self._nav("home", "Início", "home", "Ctrl+1"))
        for spec in MODULES:
            self.sidebar_layout.addWidget(self._nav(spec.key, spec.title, spec.icon, spec.shortcut))
        self.sidebar_layout.addStretch(1)
        self.sidebar_layout.addWidget(self._nav("settings", "Configurações", "settings", "Ctrl+,"))
        self.sidebar_layout.addWidget(self._nav("about", "Sobre", "info", "F1"))
        self.footer_divider = QFrame()
        self.footer_divider.setObjectName("SidebarDivider")
        self.footer_divider.setFixedHeight(1)
        self.sidebar_layout.addSpacing(12)
        self.sidebar_layout.addWidget(self.footer_divider)
        self.sidebar_layout.addSpacing(12)
        self.footer_module = label(f"  {MODULE_MARK}", "navCaption")
        self.footer_version = label(f"  Menu integrado  ·  v{__version__}", "brandSubtitle")
        self.sidebar_layout.addWidget(self.footer_module)
        self.sidebar_layout.addWidget(self.footer_version)

    def _nav(self, page: str, title: str, glyph: str, shortcut: str) -> QPushButton:
        widget = QPushButton(f"  {title}")
        widget.setProperty("role", "nav")
        widget.setObjectName(f"nav_{page}")
        widget.setCheckable(True)
        widget.setIcon(icon(glyph, "#B9C7E1", 20))
        widget.setIconSize(QSize(20, 20))
        widget.setFixedHeight(48)
        widget.setCursor(Qt.CursorShape.PointingHandCursor)
        widget.setToolTip(f"{title} ({shortcut})")
        widget.setAccessibleName(title)
        widget.clicked.connect(lambda checked=False, key=page: self.navigate_requested.emit(key))
        self.group.addButton(widget)
        self.buttons[page] = widget
        return widget

    def set_current(self, page: str) -> None:
        self.buttons[page].setChecked(True)

    def is_compact(self) -> bool:
        return self._compact

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        self.brand_button.setToolTip(
            ("Expandir menu lateral" if compact else "Recolher menu lateral")
            + " (Ctrl+B)"
        )
        if compact == self._compact:
            return

        self._compact = compact
        self.setProperty("compact", compact)
        self.setFixedWidth(COMPACT_WIDTH if compact else EXPANDED_WIDTH)
        self.sidebar_layout.setContentsMargins(
            14 if compact else 18,
            26,
            14 if compact else 18,
            20,
        )
        self.brand_words.setVisible(not compact)
        self.workspace_caption.setVisible(not compact)
        self.footer_divider.setVisible(not compact)
        self.footer_module.setVisible(not compact)
        self.footer_version.setVisible(not compact)

        for page, button in self.buttons.items():
            title = button.accessibleName()
            button.setText("" if compact else f"  {title}")
            if compact:
                button.setFixedWidth(48)
            else:
                button.setMinimumWidth(0)
                button.setMaximumWidth(16777215)

        self.style().unpolish(self)
        self.style().polish(self)
        self.update()
