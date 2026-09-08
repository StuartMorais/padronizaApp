from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QVBoxLayout

from shell.catalog import ACCENT_COLORS, ModuleSpec
from shell.widgets import button, icon_tile, label


class AppCard(QFrame):
    open_requested = Signal(str)

    def __init__(self, spec: ModuleSpec) -> None:
        super().__init__()
        self.spec = spec
        self.setProperty("role", "appCard")
        self.setProperty("accent", spec.accent)
        self.setObjectName(f"card_{spec.key}")
        self.setMinimumWidth(270)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(f"Abrir {spec.title}")
        self.setToolTip(f"Abrir {spec.title} ({spec.shortcut})")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 26, 26, 24)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(icon_tile(spec.icon, ACCENT_COLORS[spec.accent], spec.accent, 58))
        top.addStretch()
        shortcut = label(spec.shortcut, "keycap")
        top.addWidget(shortcut, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(top)
        layout.addSpacing(4)
        layout.addWidget(label(spec.title, "cardTitle"))
        layout.addWidget(label(spec.subtitle, "cardSubtitle", True))
        layout.addWidget(label(spec.description, "muted", True))
        layout.addSpacing(2)
        tags = QGridLayout()
        tags.setHorizontalSpacing(12)
        tags.setVerticalSpacing(10)
        for index, text in enumerate(spec.tags):
            item = label(f"✓  {text}", "tag")
            item.setProperty("accent", spec.accent)
            tags.addWidget(item, index // 2, index % 2)
        layout.addLayout(tags)
        layout.addStretch(1)
        layout.addSpacing(10)
        self.open_button = button(f"Abrir {spec.title}     →", "primary")
        self.open_button.setProperty("accent", spec.accent)
        self.open_button.setAccessibleName(f"Abrir {spec.title}")
        self.open_button.setObjectName(f"open_{spec.key}")
        self.open_button.clicked.connect(lambda: self.open_requested.emit(spec.key))
        layout.addWidget(self.open_button)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.open_requested.emit(self.spec.key)
        super().mouseReleaseEvent(event)
