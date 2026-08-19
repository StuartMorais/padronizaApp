from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QDragEnterEvent,
    QDragLeaveEvent,
    QDropEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class ClickableDropZone(QFrame):
    """Área reutilizável para selecionar ou arrastar um arquivo compatível."""

    browse_requested = Signal()
    file_dropped = Signal(str)
    SUPPORTED_SUFFIXES: frozenset[str] = frozenset()

    def create_browse_button(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("primaryButton")
        button.clicked.connect(self.browse_requested.emit)
        return button

    @staticmethod
    def add_drop_content(
        layout: QVBoxLayout,
        title_label: QLabel,
        subtitle_label: QLabel,
        button: QPushButton,
        *,
        spacing_before_button: int = 0,
    ) -> None:
        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        if spacing_before_button > 0:
            layout.addSpacing(spacing_before_button)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(button)
        button_row.addStretch()
        layout.addLayout(button_row)

    @classmethod
    def first_supported_path(cls, urls: Iterable[Any]) -> Path | None:
        for url in urls:
            if not url.isLocalFile():
                continue
            path = Path(url.toLocalFile())
            if (
                path.is_file()
                and path.suffix.casefold() in cls.SUPPORTED_SUFFIXES
            ):
                return path
        return None

    def set_drag_active(self, active: bool) -> None:
        self.setProperty("dragActive", active)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self.first_supported_path(event.mimeData().urls()) is None:
            event.ignore()
            return
        self.set_drag_active(True)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.set_drag_active(False)
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self.set_drag_active(False)
        path = self.first_supported_path(event.mimeData().urls())
        if path is None:
            event.ignore()
            return
        self.file_dropped.emit(str(path))
        event.acceptProposedAction()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.browse_requested.emit()
        super().mousePressEvent(event)
