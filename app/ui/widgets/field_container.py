from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets.context_help import HelpIconButton


class FieldContainer(QFrame):
    """Consistent visual shell for one generated form field.

    The editor owns only the input behavior.  This container owns the label,
    assisted-detection action, help, hint and validation message so those
    elements cannot drift into unrelated parts of the form layout.
    """

    edit_field_requested = Signal(str)

    def __init__(
        self,
        *,
        field_id: str,
        label: str,
        editor: QWidget,
        field_type: str,
        help_title: str = "",
        help_text: str = "",
        hint_text: str = "",
        assisted_detection: bool = False,
        suppress_label: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.field_id = str(field_id).strip()
        self.editor = editor
        self.setObjectName("fieldCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 7, 10, 9)
        root.setSpacing(6)

        is_checkbox = field_type == "checkbox" or isinstance(editor, QCheckBox)
        if is_checkbox:
            self._add_checkbox_editor(root, editor, help_title, help_text)
        else:
            self._add_label(root, label, help_title, help_text, suppress_label)
            self._add_assisted_action(root, assisted_detection)
            self._make_editor_expand(editor)
            root.addWidget(editor)

        # For checkbox fields the action belongs below the control instead of
        # being pushed to the far edge of the checkbox row.
        if is_checkbox:
            self._add_assisted_action(root, assisted_detection)

        self.hint_label = QLabel(hint_text)
        self.hint_label.setObjectName("fieldFormatHint")
        self.hint_label.setWordWrap(True)
        self.hint_label.setVisible(bool(str(hint_text).strip()))
        root.addWidget(self.hint_label)

        self.error_label = QLabel()
        self.error_label.setObjectName("fieldValidationMessage")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

    def _add_label(
        self,
        root: QVBoxLayout,
        label: str,
        help_title: str,
        help_text: str,
        suppress_label: bool,
    ) -> None:
        if suppress_label:
            if help_text:
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.addWidget(
                    HelpIconButton(help_title, f"<p>{escape(help_text)}</p>")
                )
                row.addStretch(1)
                root.addLayout(row)
            return

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        label_widget = QLabel(label)
        label_widget.setObjectName("fieldLabel")
        label_widget.setWordWrap(True)
        label_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        row.addWidget(label_widget, 1)

        if help_text:
            row.addWidget(
                HelpIconButton(help_title, f"<p>{escape(help_text)}</p>")
            )

        root.addLayout(row)

    def _add_checkbox_editor(
        self,
        root: QVBoxLayout,
        editor: QWidget,
        help_title: str,
        help_text: str,
    ) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(editor, 1)
        if help_text:
            row.addWidget(
                HelpIconButton(help_title, f"<p>{escape(help_text)}</p>")
            )
        root.addLayout(row)

    def _add_assisted_action(
        self,
        root: QVBoxLayout,
        assisted_detection: bool,
    ) -> None:
        if not assisted_detection or not self.field_id:
            return

        action_row = QWidget()
        action_row.setObjectName("fieldCorrectionRow")
        action_layout = QHBoxLayout(action_row)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(0)

        button = QToolButton()
        button.setObjectName("fieldCorrectionButton")
        button.setText("Ajustar campo")
        button.setToolTip(
            "Abrir este campo no editor do modelo para revisar rótulo, tipo, "
            "opções ou organização detectados automaticamente."
        )
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(
            lambda _checked=False, key=self.field_id: self.edit_field_requested.emit(key)
        )
        action_layout.addWidget(button)
        action_layout.addStretch(1)
        root.addWidget(action_row)

    @staticmethod
    def _make_editor_expand(editor: QWidget) -> None:
        policy = editor.sizePolicy()
        editor.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            policy.verticalPolicy(),
        )
