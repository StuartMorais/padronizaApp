from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


LAYOUT_LABELS = {
    "auto": "Automático",
    "grid": "Grade",
    "full_width": "Largura total",
    "choice": "Grupo de escolha",
    "form_grid": "Grade do documento",
    "table": "Tabela de registros",
}


class _LayoutDetailsDialog(QDialog):
    def __init__(self, values: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Detalhes do layout")
        self.setMinimumWidth(460)

        self.group_input = QLineEdit(str(values.get("layout_group", "")))
        self.group_label_input = QLineEdit(str(values.get("layout_group_label", "")))
        self.row_input = QLineEdit(str(values.get("layout_row", "")))
        self.row_label_input = QLineEdit(str(values.get("layout_row_label", "")))
        self.column_input = QLineEdit(str(values.get("layout_column", "")))
        self.column_index_input = QSpinBox()
        self.column_index_input.setRange(-1, 99)
        self.column_index_input.setSpecialValueText("Automático")
        try:
            index = int(values.get("layout_column_index", -1))
        except (TypeError, ValueError):
            index = -1
        self.column_index_input.setValue(index)

        self.column_span_input = QSpinBox()
        self.column_span_input.setRange(-1, 12)
        self.column_span_input.setSpecialValueText("Automático")
        try:
            span = int(values.get("layout_column_span", -1))
        except (TypeError, ValueError):
            span = -1
        self.column_span_input.setValue(span)

        self.grid_columns_input = QSpinBox()
        self.grid_columns_input.setRange(-1, 12)
        self.grid_columns_input.setSpecialValueText("Automático")
        try:
            grid_columns = int(values.get("layout_grid_columns", -1))
        except (TypeError, ValueError):
            grid_columns = -1
        self.grid_columns_input.setValue(grid_columns)

        self.choice_required = QCheckBox("Exigir uma opção no grupo")
        self.choice_required.setChecked(bool(values.get("choice_required", False)))

        explanation = QLabel(
            "Em Grupo de escolha, uma lista de opções pode ser exibida como caixas grandes "
            "e exclusivas; várias caixas de seleção também podem compartilhar o mesmo grupo. "
            "Em Grade do documento, use a mesma chave de linha para campos que aparecem "
            "lado a lado no Word; Início, Largura e Total de colunas preservam células mescladas. "
            "Tabela de registros deve ser usada somente para dados com cabeçalhos e várias linhas."
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("mutedText")

        form = QFormLayout()
        form.addRow("Grupo do layout:", self.group_input)
        form.addRow("Título do grupo:", self.group_label_input)
        form.addRow("Chave da linha:", self.row_input)
        form.addRow("Rótulo da linha:", self.row_label_input)
        form.addRow("Rótulo da coluna:", self.column_input)
        form.addRow("Início da coluna:", self.column_index_input)
        form.addRow("Largura da célula:", self.column_span_input)
        form.addRow("Total de colunas:", self.grid_columns_input)
        form.addRow("", self.choice_required)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def values(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, widget in (
            ("layout_group", self.group_input),
            ("layout_group_label", self.group_label_input),
            ("layout_row", self.row_input),
            ("layout_row_label", self.row_label_input),
            ("layout_column", self.column_input),
        ):
            value = widget.text().strip()
            if value:
                result[key] = value
        if self.column_index_input.value() >= 0:
            result["layout_column_index"] = self.column_index_input.value()
        if self.column_span_input.value() >= 0:
            result["layout_column_span"] = self.column_span_input.value()
        if self.grid_columns_input.value() >= 0:
            result["layout_grid_columns"] = self.grid_columns_input.value()
        if self.choice_required.isChecked():
            result["choice_required"] = True
        return result


class FieldLayoutEditor(QWidget):
    configuration_changed = Signal()

    def __init__(self, field: dict[str, Any] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._details: dict[str, Any] = {}

        self.layout_combo = QComboBox()
        for key, label in LAYOUT_LABELS.items():
            self.layout_combo.addItem(label, key)

        self.details_button = QPushButton("Detalhes…")
        self.details_button.setToolTip(
            "Configure grupo, linha, início e largura para grades do documento, escolhas ou tabelas."
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        layout.addWidget(self.layout_combo, 1)
        layout.addWidget(self.details_button)

        self.layout_combo.currentIndexChanged.connect(self._layout_changed)
        self.details_button.clicked.connect(self._edit_details)
        self.set_configuration(field or {})

    def set_configuration(self, field: dict[str, Any]) -> None:
        layout_type = str(field.get("layout", "auto")).strip().casefold() or "auto"
        if bool(field.get("full_width", False)) and layout_type == "auto":
            layout_type = "full_width"
        index = self.layout_combo.findData(layout_type)
        self.layout_combo.blockSignals(True)
        self.layout_combo.setCurrentIndex(index if index >= 0 else 0)
        self.layout_combo.blockSignals(False)
        self._details = {
            key: field[key]
            for key in (
                "layout_group",
                "layout_group_label",
                "layout_row",
                "layout_row_label",
                "layout_column",
                "layout_column_index",
                "layout_column_span",
                "layout_grid_columns",
                "layout_order",
                "layout_static_rows",
                "choice_required",
            )
            if key in field
        }
        self._refresh_state()

    def configuration(self) -> dict[str, Any]:
        layout_type = str(self.layout_combo.currentData() or "auto")
        result: dict[str, Any] = {"layout": layout_type}
        if layout_type == "choice":
            for key in (
                "layout_group",
                "layout_group_label",
                "choice_required",
            ):
                if key in self._details:
                    result[key] = self._details[key]
        elif layout_type in {"table", "form_grid"}:
            for key in (
                "layout_group",
                "layout_group_label",
                "layout_row",
                "layout_row_label",
                "layout_column",
                "layout_column_index",
                "layout_column_span",
                "layout_grid_columns",
                "layout_order",
                "layout_static_rows",
            ):
                if key in self._details:
                    result[key] = self._details[key]
        elif layout_type == "full_width":
            result["full_width"] = True
        return result

    def _layout_changed(self, *_args) -> None:
        self._refresh_state()
        self.configuration_changed.emit()

    def _refresh_state(self) -> None:
        layout_type = str(self.layout_combo.currentData() or "auto")
        advanced = layout_type in {"choice", "form_grid", "table"}
        self.details_button.setEnabled(advanced)
        summary = []
        if self._details.get("layout_group"):
            summary.append(f"grupo: {self._details['layout_group']}")
        if layout_type in {"form_grid", "table"} and self._details.get("layout_row"):
            summary.append(f"linha: {self._details['layout_row']}")
        if layout_type == "table" and self._details.get("layout_row_label"):
            summary.append(f"rótulo: {self._details['layout_row_label']}")
        self.details_button.setText("Detalhes…" if not summary else " • ".join(summary))

    def _edit_details(self) -> None:
        dialog = _LayoutDetailsDialog(self._details, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dialog.values()
        for key in ("layout_order", "layout_static_rows"):
            if key in self._details:
                updated[key] = self._details[key]
        self._details = updated
        self._refresh_state()
        self.configuration_changed.emit()
