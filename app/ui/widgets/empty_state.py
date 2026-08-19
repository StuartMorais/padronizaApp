from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class EmptyState(QFrame):
    """Reusable empty-state card with an icon, guidance, and optional actions."""

    def __init__(
        self,
        title: str,
        message: str,
        *,
        icon: str = "◇",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("emptyStateCard")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.setMinimumHeight(210)

        self._icon_label = QLabel(icon)
        self._icon_label.setObjectName("emptyStateIcon")
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setFixedSize(54, 54)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("emptyStateTitle")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)

        self._message_label = QLabel(message)
        self._message_label.setObjectName("emptyStateMessage")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        self._message_label.setMaximumWidth(620)

        self._actions_layout = QHBoxLayout()
        self._actions_layout.setContentsMargins(0, 4, 0, 0)
        self._actions_layout.setSpacing(8)
        self._actions_layout.addStretch()
        self._actions_layout.addStretch()

        content = QVBoxLayout(self)
        content.setContentsMargins(30, 30, 30, 30)
        content.setSpacing(10)
        content.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addStretch()
        content.addWidget(
            self._icon_label,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        content.addWidget(self._title_label)
        content.addWidget(
            self._message_label,
            0,
            Qt.AlignmentFlag.AlignHCenter,
        )
        content.addLayout(self._actions_layout)
        content.addStretch()

    def set_content(
        self,
        title: str,
        message: str,
        *,
        icon: str | None = None,
    ) -> None:
        self._title_label.setText(title)
        self._message_label.setText(message)
        if icon is not None:
            self._icon_label.setText(icon)

    def add_action(
        self,
        text: str,
        callback: Callable[[], None],
        *,
        primary: bool = False,
    ) -> QPushButton:
        button = QPushButton(text)
        if primary:
            button.setObjectName("primaryButton")
        button.clicked.connect(callback)

        insert_at = max(
            1,
            self._actions_layout.count() - 1,
        )
        self._actions_layout.insertWidget(
            insert_at,
            button,
        )
        return button
