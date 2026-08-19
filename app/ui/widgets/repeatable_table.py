from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemDelegate,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.field_metadata import (
    REPEATABLE_COLUMN_TYPES,
    dropdown_option_values,
    normalize_dropdown_options,
    normalize_repeatable_columns,
)
from app.ui.widgets.searchable_dropdown import DropdownOptionsEditor


COLUMN_TYPE_LABELS = {
    "auto_number": "Numeração automática",
    "text": "Texto",
    "multiline": "Texto com várias linhas",
    "date": "Data",
    "checkbox": "Caixa de seleção",
    "dropdown": "Lista suspensa",
    "currency": "Moeda",
    "integer": "Número inteiro",
    "decimal": "Número decimal",
    "percentage": "Porcentagem",
    "cnpj": "CNPJ",
    "cpf": "CPF",
    "cep": "CEP",
    "phone": "Telefone",
    "email": "E-mail",
}


class _PasteTableWidget(QTableWidget):
    paste_requested = Signal(str)

    def keyPressEvent(self, event) -> None:
        if event.matches(QKeySequence.StandardKey.Paste):
            clipboard = QApplication.clipboard()
            self.paste_requested.emit(clipboard.text() if clipboard else "")
            return
        super().keyPressEvent(event)


class _InlineMultilineEditor(QPlainTextEdit):
    """Multiline editor that stays inside the selected table cell."""

    commit_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("repeatableInlineMultilineEditor")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setTabChangesFocus(True)
        self.setPlaceholderText("Digite diretamente nesta célula...")

    def keyPressEvent(self, event) -> None:
        if (
            event.key()
            in {Qt.Key.Key_Return, Qt.Key.Key_Enter}
            and event.modifiers()
            & Qt.KeyboardModifier.ControlModifier
        ):
            self.commit_requested.emit()
            event.accept()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class _RepeatableCellDelegate(QStyledItemDelegate):
    """Creates direct, in-cell editors for repeatable-table columns."""

    def __init__(
        self,
        columns: list[dict[str, Any]],
        table: QTableWidget,
    ) -> None:
        super().__init__(table)
        self.columns = columns
        self.table = table

    def createEditor(self, parent, option, index):
        column_type = self._column_type(index.column())
        if column_type in {"auto_number", "checkbox"}:
            return None

        if column_type == "dropdown":
            editor = QComboBox(parent)
            editor.setObjectName("repeatableInlineDropdown")
            editor.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            editor.setMaxVisibleItems(14)
            editor.addItem("Selecionar...", "")
            column = self.columns[index.column()]
            for option_data in normalize_dropdown_options(
                column.get("options", [])
            ):
                editor.addItem(
                    option_data["label"],
                    option_data["value"],
                )
                editor.setItemData(
                    editor.count() - 1,
                    option_data["value"],
                    Qt.ItemDataRole.ToolTipRole,
                )
            editor.activated.connect(
                lambda _selected, current=editor: (
                    self._commit_and_close(current)
                )
            )
            return editor

        if column_type == "multiline":
            editor = _InlineMultilineEditor(parent)
            editor.setProperty(
                "previousRowHeight",
                self.table.rowHeight(index.row()),
            )
            self.table.setRowHeight(
                index.row(),
                max(112, self.table.rowHeight(index.row())),
            )
            editor.commit_requested.connect(
                lambda current=editor: self._commit_and_close(current)
            )
            editor.cancel_requested.connect(
                lambda current=editor: self._cancel_and_close(current)
            )
            return editor

        return super().createEditor(parent, option, index)

    def setEditorData(self, editor, index) -> None:
        if isinstance(editor, QComboBox):
            current_value = str(
                index.data(Qt.ItemDataRole.UserRole) or ""
            )
            selected_index = editor.findData(current_value)
            editor.setCurrentIndex(max(0, selected_index))
            editor.setToolTip(current_value)
            return

        if isinstance(editor, QPlainTextEdit):
            editor.setPlainText(
                str(index.data(Qt.ItemDataRole.EditRole) or "")
            )
            cursor = editor.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            editor.setTextCursor(cursor)
            return

        super().setEditorData(editor, index)

    def setModelData(self, editor, model, index) -> None:
        if isinstance(editor, QComboBox):
            selected_value = str(editor.currentData() or "").strip()
            selected_label = (
                editor.currentText()
                if selected_value
                else "Selecionar..."
            )
            model.setData(
                index,
                selected_label,
                Qt.ItemDataRole.EditRole,
            )
            model.setData(
                index,
                selected_value,
                Qt.ItemDataRole.UserRole,
            )
            model.setData(
                index,
                selected_value
                or "Clique na célula para escolher uma opção.",
                Qt.ItemDataRole.ToolTipRole,
            )
            return

        if isinstance(editor, QPlainTextEdit):
            text = editor.toPlainText().strip()
            model.setData(
                index,
                text,
                Qt.ItemDataRole.EditRole,
            )
            model.setData(
                index,
                text
                or (
                    "Clique na célula para digitar. "
                    "Ctrl+Enter conclui a edição."
                ),
                Qt.ItemDataRole.ToolTipRole,
            )
            return

        super().setModelData(editor, model, index)

    def updateEditorGeometry(self, editor, option, index) -> None:
        editor.setGeometry(option.rect)

    def destroyEditor(self, editor, index) -> None:
        if isinstance(editor, _InlineMultilineEditor):
            previous_height = editor.property("previousRowHeight")
            try:
                restored_height = max(48, int(previous_height))
            except (TypeError, ValueError):
                restored_height = 48
            self.table.setRowHeight(index.row(), restored_height)
        super().destroyEditor(editor, index)

    def _column_type(self, column_index: int) -> str:
        if not (0 <= column_index < len(self.columns)):
            return "text"
        return str(self.columns[column_index].get("type", "text"))

    def _commit_and_close(self, editor: QWidget) -> None:
        self.commitData.emit(editor)
        self.closeEditor.emit(
            editor,
            QAbstractItemDelegate.EndEditHint.NoHint,
        )

    def _cancel_and_close(self, editor: QWidget) -> None:
        self.closeEditor.emit(
            editor,
            QAbstractItemDelegate.EndEditHint.RevertModelCache,
        )


class RepeatableTableWidget(QFrame):
    """Editable rows for a Word table marked with ``{{repeat:...}}``."""

    values_changed = Signal()

    def __init__(self, field: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("repeatableTableEditor")
        self.field = dict(field)
        self.columns = normalize_repeatable_columns(field.get("columns", []))
        self.minimum_rows = max(0, int(field.get("minimum_rows", 1) or 0))
        self.numbering_padding = max(1, int(field.get("numbering_padding", 2) or 2))
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(6)

        self.add_button = QPushButton("Adicionar item")
        self.duplicate_button = QPushButton("Duplicar item")
        self.remove_button = QPushButton("Remover item")
        self.up_button = QPushButton("Mover para cima")
        self.down_button = QPushButton("Mover para baixo")
        self.paste_button = QPushButton("Colar do Excel")

        self.add_button.clicked.connect(self.add_row)
        self.duplicate_button.clicked.connect(self.duplicate_selected_row)
        self.remove_button.clicked.connect(self.remove_selected_rows)
        self.up_button.clicked.connect(lambda: self.move_selected_row(-1))
        self.down_button.clicked.connect(lambda: self.move_selected_row(1))
        self.paste_button.clicked.connect(self._paste_from_clipboard)

        for button in (
            self.add_button,
            self.duplicate_button,
            self.remove_button,
            self.up_button,
            self.down_button,
            self.paste_button,
        ):
            toolbar.addWidget(button)
        toolbar.addStretch()
        root.addLayout(toolbar)

        self.table = _PasteTableWidget(0, len(self.columns))
        self.table.setObjectName("repeatableDataTable")
        self.table.setHorizontalHeaderLabels(
            [str(column.get("label", column.get("id", ""))) for column in self.columns]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        self.table.setTabKeyNavigation(True)
        self.table.setWordWrap(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(False)
        self._cell_delegate = _RepeatableCellDelegate(
            self.columns,
            self.table,
        )
        self.table.setItemDelegate(self._cell_delegate)
        self.table.itemChanged.connect(self._item_changed)
        self.table.currentCellChanged.connect(
            lambda *_args: self._refresh_state()
        )
        self.table.paste_requested.connect(self.paste_text)
        root.addWidget(self.table, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel()
        self.status_label.setObjectName("repeatableTableStatus")
        self.status_label.setWordWrap(True)
        footer.addWidget(self.status_label, 1)
        root.addLayout(footer)

        self._configure_columns()
        for _index in range(self.minimum_rows):
            self._append_row({})
        self._refresh_state()

    def rows(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row_index in range(self.table.rowCount()):
            row = self._row_values(row_index)
            if self._row_is_meaningful(row):
                row["__row_number__"] = (
                    f"{len(result) + 1:0{self.numbering_padding}d}"
                )
                result.append(row)
        return result

    def set_rows(self, rows: Any, *, emit_signal: bool = False) -> None:
        normalized_rows = [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        self._loading = True
        try:
            self.table.setRowCount(0)
            for row in normalized_rows:
                self._append_row(row)
            while self.table.rowCount() < self.minimum_rows:
                self._append_row({})
        finally:
            self._loading = False
        self._renumber_rows()
        self._refresh_state()
        if emit_signal:
            self.values_changed.emit()

    def clear(self, *, emit_signal: bool = False) -> None:
        self.set_rows([], emit_signal=emit_signal)

    def has_meaningful_values(self) -> bool:
        return bool(self.rows())

    def focus_table(self) -> None:
        self.table.setFocus(Qt.FocusReason.OtherFocusReason)
        if self.table.rowCount() and self.table.columnCount():
            self.table.setCurrentCell(0, self._first_editable_column())

    def add_row(self, values: dict[str, Any] | None = None) -> None:
        row = self._append_row(values or {})
        first_column = self._first_editable_column()
        self.table.setCurrentCell(row, first_column)
        item = self.table.item(row, first_column)
        if item is not None:
            self.table.scrollToItem(item)
        self._emit_changed()

    def duplicate_selected_row(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        values = self._row_values(row)
        inserted = self._insert_row(row + 1, values)
        self.table.selectRow(inserted)
        self._emit_changed()

    def remove_selected_rows(self) -> None:
        rows = sorted(
            {index.row() for index in self.table.selectedIndexes()},
            reverse=True,
        )
        if not rows and self.table.currentRow() >= 0:
            rows = [self.table.currentRow()]
        if not rows:
            return

        for row in rows:
            self.table.removeRow(row)
        while self.table.rowCount() < self.minimum_rows:
            self._append_row({})
        self._renumber_rows()
        self._emit_changed()

    def move_selected_row(self, direction: int) -> None:
        row = self.table.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= self.table.rowCount():
            return

        rows = [self._row_values(index) for index in range(self.table.rowCount())]
        rows[row], rows[target] = rows[target], rows[row]
        self.set_rows(rows)
        self.table.selectRow(target)
        self._emit_changed()

    def paste_text(self, text: str) -> None:
        rows = [line.split("\t") for line in str(text or "").splitlines() if line.strip()]
        if not rows:
            return

        start_row = max(0, self.table.currentRow())
        start_column = max(0, self.table.currentColumn())
        if self.table.rowCount() == 0:
            start_row = 0
        while self.table.rowCount() < start_row + len(rows):
            self._append_row({})

        self._loading = True
        try:
            for row_offset, pasted_row in enumerate(rows):
                target_row = start_row + row_offset
                target_column = start_column
                for raw_value in pasted_row:
                    while (
                        target_column < len(self.columns)
                        and self.columns[target_column].get("type") == "auto_number"
                    ):
                        target_column += 1
                    if target_column >= len(self.columns):
                        break
                    self._set_cell_value(target_row, target_column, raw_value)
                    target_column += 1
        finally:
            self._loading = False
        self._renumber_rows()
        self._emit_changed()

    def _paste_from_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        self.paste_text(clipboard.text() if clipboard else "")

    def _configure_columns(self) -> None:
        header = self.table.horizontalHeader()
        for index, column in enumerate(self.columns):
            column_type = str(column.get("type", "text"))
            if column_type == "auto_number":
                width = 70
            elif column_type in {"integer", "decimal", "percentage", "date"}:
                width = 115
            elif column_type in {"checkbox"}:
                width = 90
            elif column_type in {"multiline"}:
                width = 300
            else:
                width = int(column.get("width", 180) or 180)
            self.table.setColumnWidth(index, max(70, width))
            header_item = self.table.horizontalHeaderItem(index)
            if header_item is not None:
                marker = str(column.get("marker", "")).strip()
                hint = COLUMN_TYPE_LABELS.get(column_type, column_type)
                if marker:
                    hint += f"\nMarcador: {{{{{marker}}}}}"
                header_item.setToolTip(hint)
        header.setStretchLastSection(True)

    def _append_row(self, values: dict[str, Any]) -> int:
        return self._insert_row(self.table.rowCount(), values)

    def _insert_row(self, row: int, values: dict[str, Any]) -> int:
        previous_loading = self._loading
        self._loading = True
        try:
            self.table.insertRow(row)
            for column_index, column in enumerate(self.columns):
                self._create_cell(row, column_index, column, values.get(str(column.get("id", ""))))
            self.table.setRowHeight(row, 48)
        finally:
            self._loading = previous_loading
        self._renumber_rows()
        self._refresh_state()
        return row

    def _create_cell(
        self,
        row: int,
        column_index: int,
        column: dict[str, Any],
        value: Any,
    ) -> None:
        column_type = str(column.get("type", "text"))
        item = QTableWidgetItem()
        item.setTextAlignment(
            Qt.AlignmentFlag.AlignVCenter
            | (
                Qt.AlignmentFlag.AlignCenter
                if column_type in {
                    "auto_number",
                    "checkbox",
                    "integer",
                    "decimal",
                    "percentage",
                }
                else Qt.AlignmentFlag.AlignLeft
            )
        )

        if column_type == "auto_number":
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        elif column_type == "checkbox":
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(
                Qt.CheckState.Checked if bool(value) else Qt.CheckState.Unchecked
            )
        elif column_type == "dropdown":
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
            )
            self._set_dropdown_item(item, column, value)
        elif column_type == "multiline":
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
            )
            item.setText(str(value or ""))
            item.setToolTip(
                (str(value or "") + "\n\n" if value else "")
                + (
                    "Clique na célula e digite diretamente. "
                    "Enter cria uma nova linha e Ctrl+Enter conclui."
                )
            )
        else:
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsEditable
            )
            item.setText(str(value or ""))
            item.setToolTip(str(value or ""))

        self.table.setItem(row, column_index, item)

    def _row_values(self, row: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for column_index, column in enumerate(self.columns):
            column_id = str(column.get("id", "")).strip()
            column_type = str(column.get("type", "text"))
            if not column_id or column_type == "auto_number":
                continue
            item = self.table.item(row, column_index)
            if item is None:
                value: Any = False if column_type == "checkbox" else ""
            elif column_type == "checkbox":
                value = item.checkState() == Qt.CheckState.Checked
            elif column_type == "dropdown":
                value = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            else:
                value = item.text().strip()
            result[column_id] = value
        return result

    @staticmethod
    def _row_is_meaningful(row: dict[str, Any]) -> bool:
        return any(
            bool(value) if isinstance(value, bool) else bool(str(value or "").strip())
            for key, value in row.items()
            if not str(key).startswith("__")
        )

    def _set_cell_value(self, row: int, column_index: int, value: Any) -> None:
        if row < 0 or column_index < 0 or column_index >= len(self.columns):
            return
        item = self.table.item(row, column_index)
        if item is None:
            return
        column = self.columns[column_index]
        column_type = str(column.get("type", "text"))
        if column_type == "auto_number":
            return
        if column_type == "checkbox":
            checked = str(value or "").strip().casefold() in {
                "1", "x", "sim", "s", "yes", "true", "☑", "marcado",
            }
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            return
        if column_type == "dropdown":
            self._set_dropdown_item(item, column, value)
            return
        item.setText(str(value or "").strip())
        item.setToolTip(str(value or "").strip())

    @staticmethod
    def _set_dropdown_item(item: QTableWidgetItem, column: dict[str, Any], value: Any) -> None:
        text = str(value or "").strip()
        options = normalize_dropdown_options(column.get("options", []))
        matched = next(
            (
                option
                for option in options
                if text in {option["value"], option["label"]}
            ),
            None,
        )
        stored = matched["value"] if matched else ""
        label = matched["label"] if matched else "Selecionar..."
        item.setData(Qt.ItemDataRole.UserRole, stored)
        item.setText(label)
        item.setToolTip(
            stored or "Clique na célula para escolher uma opção."
        )

    def _item_changed(self, _item: QTableWidgetItem) -> None:
        if self._loading:
            return
        self._refresh_state()
        self.values_changed.emit()

    def _emit_changed(self) -> None:
        if self._loading:
            return
        self._refresh_state()
        self.values_changed.emit()

    def _renumber_rows(self) -> None:
        previous_loading = self._loading
        self._loading = True
        try:
            for row in range(self.table.rowCount()):
                for column_index, column in enumerate(self.columns):
                    if str(column.get("type", "text")) != "auto_number":
                        continue
                    item = self.table.item(row, column_index)
                    if item is not None:
                        item.setText(f"{row + 1:0{self.numbering_padding}d}")
        finally:
            self._loading = previous_loading

    def _refresh_state(self) -> None:
        meaningful = len(self.rows())
        total = self.table.rowCount()
        minimum_text = (
            f" Mínimo: {self.minimum_rows}."
            if self.minimum_rows
            else ""
        )
        self.status_label.setText(
            f"{meaningful} item(ns) preenchido(s); {total} linha(s) visível(is)."
            f"{minimum_text} Digite diretamente nas células ou use Ctrl+V "
            "para colar dados tabulados. Em textos longos, Ctrl+Enter conclui."
        )
        has_selection = self.table.currentRow() >= 0
        self.duplicate_button.setEnabled(has_selection)
        self.remove_button.setEnabled(has_selection)
        self.up_button.setEnabled(has_selection and self.table.currentRow() > 0)
        self.down_button.setEnabled(
            has_selection and self.table.currentRow() < self.table.rowCount() - 1
        )

    def _first_editable_column(self) -> int:
        for index, column in enumerate(self.columns):
            if str(column.get("type", "text")) != "auto_number":
                return index
        return 0


class RepeatableColumnsEditor(QWidget):
    columns_changed = Signal()

    def __init__(
        self,
        columns: Any = None,
        *,
        minimum_rows: int = 1,
        numbering_padding: int = 2,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._columns = normalize_repeatable_columns(columns)
        self._minimum_rows = max(0, int(minimum_rows or 0))
        self._numbering_padding = max(1, int(numbering_padding or 2))

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.summary = QLineEdit()
        self.summary.setReadOnly(True)
        self.summary.setObjectName("repeatableColumnsSummary")
        layout.addWidget(self.summary, 1)

        self.edit_button = QPushButton("Editar...")
        self.edit_button.setObjectName("repeatableColumnsEditButton")
        self.edit_button.clicked.connect(self._edit_columns)
        layout.addWidget(self.edit_button)
        self._refresh_summary()

    def columns(self) -> list[dict[str, Any]]:
        return deepcopy(self._columns)

    def minimum_rows(self) -> int:
        return self._minimum_rows

    def numbering_padding(self) -> int:
        return self._numbering_padding

    def _edit_columns(self) -> None:
        dialog = RepeatableColumnsDialog(
            self._columns,
            minimum_rows=self._minimum_rows,
            numbering_padding=self._numbering_padding,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._columns = dialog.columns()
        self._minimum_rows = dialog.minimum_rows()
        self._numbering_padding = dialog.numbering_padding()
        self._refresh_summary()
        self.columns_changed.emit()

    def _refresh_summary(self) -> None:
        count = len(self._columns)
        if not count:
            self.summary.clear()
            self.summary.setPlaceholderText("Nenhuma coluna")
            self.summary.setToolTip("")
            return
        labels = [str(column.get("label", column.get("id", ""))) for column in self._columns[:3]]
        text = f"{count} coluna(s): " + "; ".join(labels)
        if count > 3:
            text += "; …"
        self.summary.setText(text)
        self.summary.setToolTip(
            "\n".join(
                f"{column.get('label', column.get('id', ''))} — "
                f"{COLUMN_TYPE_LABELS.get(str(column.get('type', 'text')), column.get('type', 'text'))}"
                for column in self._columns
            )
        )


class FieldConfigurationEditor(QWidget):
    configuration_changed = Signal()

    def __init__(
        self,
        field_type: str = "text",
        *,
        options: Any = None,
        columns: Any = None,
        minimum_rows: int = 1,
        numbering_padding: int = 2,
        parent=None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.stack = QStackedWidget()
        self.empty = QLineEdit()
        self.empty.setReadOnly(True)
        self.empty.setPlaceholderText("Sem configuração adicional")
        self.dropdown = DropdownOptionsEditor(options)
        self.repeatable = RepeatableColumnsEditor(
            columns,
            minimum_rows=minimum_rows,
            numbering_padding=numbering_padding,
        )
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.dropdown)
        self.stack.addWidget(self.repeatable)
        layout.addWidget(self.stack)

        self.dropdown.options_changed.connect(
            self.configuration_changed.emit
        )
        self.repeatable.columns_changed.connect(
            self.configuration_changed.emit
        )
        self.set_field_type(field_type)

    def set_field_type(self, field_type: str) -> None:
        if field_type == "dropdown":
            self.stack.setCurrentWidget(self.dropdown)
        elif field_type == "repeatable_table":
            self.stack.setCurrentWidget(self.repeatable)
        else:
            self.empty.setPlaceholderText("Sem configuração adicional")
            self.stack.setCurrentWidget(self.empty)

    def options(self) -> list[str | dict[str, str]]:
        return self.dropdown.options()

    def columns(self) -> list[dict[str, Any]]:
        return self.repeatable.columns()

    def minimum_rows(self) -> int:
        return self.repeatable.minimum_rows()

    def numbering_padding(self) -> int:
        return self.repeatable.numbering_padding()


class RepeatableColumnsDialog(QDialog):
    def __init__(
        self,
        columns: Any = None,
        *,
        minimum_rows: int = 1,
        numbering_padding: int = 2,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Editar colunas da tabela repetível")
        self.resize(980, 620)
        self.setMinimumSize(760, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(10)

        intro = QLabel(
            "Cada coluna corresponde a um marcador na linha modelo do DOCX. "
            "A numeração automática usa {{row.number}}."
        )
        intro.setObjectName("mutedText")
        intro.setWordWrap(True)
        root.addWidget(intro)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel("Mínimo de itens:"))
        self.minimum_rows_input = QSpinBox()
        self.minimum_rows_input.setRange(0, 999)
        self.minimum_rows_input.setValue(max(0, int(minimum_rows or 0)))
        settings_row.addWidget(self.minimum_rows_input)
        settings_row.addSpacing(18)
        settings_row.addWidget(QLabel("Dígitos da numeração:"))
        self.padding_input = QSpinBox()
        self.padding_input.setRange(1, 6)
        self.padding_input.setValue(max(1, int(numbering_padding or 2)))
        settings_row.addWidget(self.padding_input)
        settings_row.addStretch()
        root.addLayout(settings_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["ID da coluna", "Rótulo", "Tipo", "Obrigatório", "Opções"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setColumnWidth(0, 170)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(2, 170)
        self.table.setColumnWidth(3, 95)
        self.table.setColumnWidth(4, 260)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        add_button = QPushButton("Adicionar coluna")
        remove_button = QPushButton("Remover")
        up_button = QPushButton("Mover para cima")
        down_button = QPushButton("Mover para baixo")
        add_button.clicked.connect(lambda: self._insert_column({"type": "text", "required": False}))
        remove_button.clicked.connect(self._remove_column)
        up_button.clicked.connect(lambda: self._move_column(-1))
        down_button.clicked.connect(lambda: self._move_column(1))
        actions.addWidget(add_button)
        actions.addWidget(remove_button)
        actions.addStretch()
        actions.addWidget(up_button)
        actions.addWidget(down_button)
        root.addLayout(actions)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Salvar colunas")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaryButton")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        for column in normalize_repeatable_columns(columns):
            self._insert_column(column)

    def columns(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in range(self.table.rowCount()):
            id_item = self.table.item(row, 0)
            label_item = self.table.item(row, 1)
            type_combo = self.table.cellWidget(row, 2)
            required_container = self.table.cellWidget(row, 3)
            options_editor = self.table.cellWidget(row, 4)
            required = required_container.findChild(QCheckBox) if required_container else None
            column_type = str(type_combo.currentData() or "text") if isinstance(type_combo, QComboBox) else "text"
            column_id = id_item.text().strip() if id_item else ""
            label = label_item.text().strip() if label_item else ""
            column: dict[str, Any] = {
                "id": column_id,
                "label": label or column_id.replace("_", " ").title(),
                "type": column_type,
                "required": False if column_type in {"auto_number", "checkbox"} else bool(required and required.isChecked()),
            }
            marker = str(id_item.data(Qt.ItemDataRole.UserRole) or "") if id_item else ""
            if marker:
                column["marker"] = marker
            if column_type == "dropdown" and isinstance(options_editor, DropdownOptionsEditor):
                column["options"] = options_editor.options()
            result.append(column)
        return normalize_repeatable_columns(result)

    def minimum_rows(self) -> int:
        return self.minimum_rows_input.value()

    def numbering_padding(self) -> int:
        return self.padding_input.value()

    def _insert_column(self, column: dict[str, Any]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)

        id_item = QTableWidgetItem(str(column.get("id", "")))
        id_item.setData(Qt.ItemDataRole.UserRole, str(column.get("marker", "")))
        self.table.setItem(row, 0, id_item)
        self.table.setItem(row, 1, QTableWidgetItem(str(column.get("label", ""))))

        type_combo = QComboBox()
        for type_id in REPEATABLE_COLUMN_TYPES:
            type_combo.addItem(COLUMN_TYPE_LABELS.get(type_id, type_id), type_id)
        index = type_combo.findData(str(column.get("type", "text")))
        type_combo.setCurrentIndex(index if index >= 0 else type_combo.findData("text"))
        self.table.setCellWidget(row, 2, type_combo)

        required = QCheckBox()
        required.setChecked(bool(column.get("required", False)))
        required_container = QWidget()
        required_layout = QHBoxLayout(required_container)
        required_layout.setContentsMargins(0, 0, 0, 0)
        required_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        required_layout.addWidget(required)
        self.table.setCellWidget(row, 3, required_container)

        options = DropdownOptionsEditor(column.get("options", []))
        self.table.setCellWidget(row, 4, options)

        type_combo.currentIndexChanged.connect(
            lambda _index, combo=type_combo, req=required, opt=options: self._column_type_changed(
                str(combo.currentData() or "text"), req, opt
            )
        )
        self._column_type_changed(str(column.get("type", "text")), required, options)

    @staticmethod
    def _column_type_changed(
        column_type: str,
        required: QCheckBox,
        options: DropdownOptionsEditor,
    ) -> None:
        options.setEnabled(column_type == "dropdown")
        required.setEnabled(column_type not in {"auto_number", "checkbox"})
        if column_type in {"auto_number", "checkbox"}:
            required.setChecked(False)

    def _remove_column(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _move_column(self, direction: int) -> None:
        row = self.table.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= self.table.rowCount():
            return
        columns = self.columns()
        columns[row], columns[target] = columns[target], columns[row]
        self.table.setRowCount(0)
        for column in columns:
            self._insert_column(column)
        self.table.selectRow(target)

    def _accept(self) -> None:
        columns = self.columns()
        if not columns:
            QMessageBox.warning(self, "Colunas obrigatórias", "Adicione pelo menos uma coluna.")
            return
        ids = [str(column.get("id", "")).strip() for column in columns]
        if any(not column_id for column_id in ids):
            QMessageBox.warning(self, "ID obrigatório", "Todas as colunas precisam de um ID.")
            return
        if len(ids) != len(set(ids)):
            QMessageBox.warning(self, "ID duplicado", "Os IDs das colunas devem ser exclusivos.")
            return
        for column in columns:
            if column.get("type") == "dropdown" and not dropdown_option_values(column.get("options", [])):
                QMessageBox.warning(
                    self,
                    "Opções obrigatórias",
                    f"A coluna '{column.get('label', column.get('id'))}' precisa de opções.",
                )
                return
        self.accept()
