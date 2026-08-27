from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class RepeatableListWidget(QWidget):
    """Simple add/remove editor for semantic repeatable-list fields."""

    values_changed = Signal()

    def __init__(self, field: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.field = dict(field)
        self._rows: list[tuple[QWidget, QLineEdit]] = []
        self._updating = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self.rows_layout = QVBoxLayout()
        self.rows_layout.setSpacing(5)
        root.addLayout(self.rows_layout)

        actions = QHBoxLayout()
        self.add_button = QPushButton("+ Adicionar item")
        self.add_button.clicked.connect(lambda: self.add_item(""))
        actions.addWidget(self.add_button)
        actions.addStretch()
        root.addLayout(actions)

        defaults = field.get("default_value", [])
        if isinstance(defaults, list) and defaults:
            self.set_items(defaults, emit_signal=False)
        else:
            minimum = max(1, int(field.get("minimum_items", 1) or 1))
            for _ in range(minimum):
                self.add_item("", emit_signal=False)

    def items(self) -> list[str]:
        return [
            editor.text().strip()
            for _row, editor in self._rows
            if editor.text().strip()
        ]

    def set_items(self, values: list[Any], *, emit_signal: bool = True) -> None:
        self._updating = True
        try:
            self.clear(emit_signal=False)
            cleaned = [str(value or "").strip() for value in values]
            cleaned = [value for value in cleaned if value]
            for value in cleaned:
                self.add_item(value, emit_signal=False)
            if not self._rows:
                self.add_item("", emit_signal=False)
        finally:
            self._updating = False
        if emit_signal:
            self.values_changed.emit()

    def add_item(self, value: str = "", *, emit_signal: bool = True) -> None:
        row = QWidget(self)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        number = QLabel(str(len(self._rows) + 1))
        number.setMinimumWidth(24)
        layout.addWidget(number)

        editor = QLineEdit()
        editor.setPlaceholderText(str(self.field.get("item_placeholder", "Informe um item...")))
        editor.setText(str(value or ""))
        editor.textChanged.connect(self._changed)
        layout.addWidget(editor, 1)

        remove = QToolButton()
        remove.setText("Remover")
        remove.setToolTip("Remover este item")
        remove.clicked.connect(lambda _checked=False, target=row: self._remove_row(target))
        layout.addWidget(remove)

        row.setProperty("repeatableListNumberLabel", number)
        self.rows_layout.addWidget(row)
        self._rows.append((row, editor))
        if emit_signal and not self._updating:
            self.values_changed.emit()

    def clear(self, *, emit_signal: bool = True) -> None:
        for row, _editor in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()
        if emit_signal and not self._updating:
            self.values_changed.emit()

    def focus_list(self) -> None:
        if self._rows:
            self._rows[0][1].setFocus()

    def _remove_row(self, target: QWidget) -> None:
        retained: list[tuple[QWidget, QLineEdit]] = []
        for row, editor in self._rows:
            if row is target:
                row.setParent(None)
                row.deleteLater()
            else:
                retained.append((row, editor))
        self._rows = retained
        if not self._rows:
            self.add_item("", emit_signal=False)
        self._renumber()
        self.values_changed.emit()

    def _renumber(self) -> None:
        for index, (row, _editor) in enumerate(self._rows, start=1):
            label = row.property("repeatableListNumberLabel")
            if isinstance(label, QLabel):
                label.setText(str(index))

    def _changed(self, *_args) -> None:
        if not self._updating:
            self.values_changed.emit()
