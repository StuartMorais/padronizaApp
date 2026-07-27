from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLineEdit

from app.field_utils import format_input


class SmartLineEdit(QLineEdit):
    """Line edit with lightweight local masks for common Brazilian fields."""

    value_changed = Signal()

    def __init__(self, field_type: str = "text", parent=None) -> None:
        super().__init__(parent)
        self.field_type = str(field_type)
        self._formatting = False
        self.textEdited.connect(self._format_edited_text)
        self.textChanged.connect(lambda _text: self.value_changed.emit())

    def _format_edited_text(self, text: str) -> None:
        if self._formatting:
            return

        if self.field_type not in {
            "cnpj",
            "cpf",
            "cep",
            "phone",
            "currency",
            "integer",
            "percentage",
        }:
            return

        formatted = format_input(self.field_type, text)
        if formatted == text:
            return

        self._formatting = True
        try:
            self.setText(formatted)
            self.setCursorPosition(len(formatted))
        finally:
            self._formatting = False

    def set_value(self, value) -> None:
        formatted = format_input(self.field_type, value)
        self.setText(formatted)
