from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from shell import __version__
from shell.catalog import MODULES
from shell.icons import icon
from shell.widgets import label


class Sidebar(QFrame):
    navigate_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("Sidebar")
        self.setFixedWidth(224)
        self.buttons: dict[str, QPushButton] = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 26, 18, 20)
        layout.setSpacing(8)

        brand = QWidget()
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(8, 0, 0, 0)
        brand_row.setSpacing(12)
        glyph = label("")
        glyph.setFixedSize(32, 32)
        glyph.setPixmap(icon("grid", "#92B2FF", 30).pixmap(30, 30))
        brand_row.addWidget(glyph)
        brand_words = QVBoxLayout()
        brand_words.setSpacing(2)
        brand_words.addWidget(label("Office Tools", "brand"))
        brand_words.addWidget(label("Seu trabalho, conectado.", "brandSubtitle"))
        brand_row.addLayout(brand_words)
        layout.addWidget(brand)
        layout.addSpacing(38)
        layout.addWidget(label("  ESPAÇO DE TRABALHO", "navCaption"))
        layout.addSpacing(4)
        layout.addWidget(self._nav("home", "Início", "home", "Ctrl+1"))
        for spec in MODULES:
            layout.addWidget(self._nav(spec.key, spec.title, spec.icon, spec.shortcut))
        layout.addStretch(1)
        layout.addWidget(self._nav("settings", "Configurações", "settings", "Ctrl+,"))
        layout.addWidget(self._nav("about", "Sobre", "info", "F1"))
        line = QFrame()
        line.setObjectName("SidebarDivider")
        line.setFixedHeight(1)
        layout.addSpacing(12)
        layout.addWidget(line)
        layout.addSpacing(12)
        layout.addWidget(label("  PADRONIZA + CHECKLIST", "navCaption"))
        layout.addWidget(label(f"  Menu integrado  ·  v{__version__}", "brandSubtitle"))

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
