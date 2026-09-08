from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from shell.icons import icon


def label(text: str, role: str = "body", wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    widget.setProperty("role", role)
    widget.setWordWrap(wrap)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    return widget


def icon_tile(name: str, color: str, tone: str = "neutral", size: int = 52) -> QLabel:
    widget = QLabel()
    widget.setProperty("role", "iconTile")
    widget.setProperty("tone", tone)
    widget.setFixedSize(size, size)
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    glyph_size = round(size * 0.55)
    widget.setPixmap(icon(name, color, glyph_size).pixmap(glyph_size, glyph_size))
    return widget


def button(text: str, role: str = "secondary") -> QPushButton:
    widget = QPushButton(text)
    widget.setProperty("role", role)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setMinimumHeight(42)
    return widget


class ScrollPage(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("ShellScroll")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        canvas = QWidget()
        canvas.setObjectName("ShellCanvas")
        outer = QHBoxLayout(canvas)
        outer.setContentsMargins(32, 30, 32, 26)
        outer.setSpacing(0)
        self.content = QWidget()
        self.content.setMaximumWidth(1080)
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(22)
        outer.addWidget(self.content, 1)
        self.setWidget(canvas)


def panel() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setProperty("role", "panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(28, 26, 28, 26)
    layout.setSpacing(16)
    return frame, layout


def page_heading(title: str, description: str) -> QWidget:
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    layout.addWidget(label(title, "pageTitle", True))
    layout.addWidget(label(description, "muted", True))
    return widget
