from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.automatic_field_detector import candidate_source_label
from app.field_utils import FIELD_TYPE_ORDER, compact_dropdown_options


VALID_FIELD_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")


class AutomaticDetectionDialog(QDialog):
    """Review automatic DOCX field suggestions before tags are inserted."""

    TYPE_LABELS = {
        "text": "Texto",
        "multiline": "Texto com várias linhas",
        "date": "Data",
        "checkbox": "Caixa de seleção",
        "dropdown": "Lista / escolha",
        "currency": "Moeda",
        "integer": "Número inteiro",
        "decimal": "Número decimal",
        "percentage": "Porcentagem",
        "cnpj": "CNPJ",
        "cpf": "CPF",
        "cep": "CEP",
        "phone": "Telefone",
        "email": "E-mail",
        "checkbox_group": "Grupo de caixas de seleção",
        "repeatable_table": "Tabela repetível",
    }

    def __init__(
        self,
        candidates: list[dict[str, Any]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._candidates = [deepcopy(item) for item in candidates]
        self.setWindowTitle("Detectar campos sem tags")
        self.resize(1180, 720)
        self.setMinimumSize(820, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Revise as áreas que parecem precisar de preenchimento")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        description = QLabel(
            "A detecção automática é assistida e pode interpretar alguns elementos do documento "
            "de forma incorreta ou deixar campos sem identificar. As tags existentes continuam "
            "sendo prioritárias. Apenas as sugestões marcadas serão convertidas em tags numa "
            "cópia de trabalho; sugestões de baixa confiança ficam desmarcadas. Você pode editar "
            "o modelo depois, inclusive durante o uso, se encontrar algo que precise de ajuste."
        )
        description.setWordWrap(True)
        root.addWidget(description)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            [
                "Usar",
                "Confiança",
                "Origem",
                "ID do campo",
                "Rótulo",
                "Tipo",
                "Trecho encontrado",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.doubleClicked.connect(self._edit_selected)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(3, 235)
        self.table.setColumnWidth(4, 260)
        root.addWidget(self.table, 1)

        tools = QHBoxLayout()
        self.high_confidence_button = QPushButton("Marcar alta confiança")
        self.high_confidence_button.clicked.connect(self._select_high_confidence)
        tools.addWidget(self.high_confidence_button)

        self.clear_button = QPushButton("Desmarcar todas")
        self.clear_button.clicked.connect(self._clear_selection)
        tools.addWidget(self.clear_button)

        self.edit_button = QPushButton("Editar sugestão...")
        self.edit_button.clicked.connect(self._edit_selected)
        tools.addWidget(self.edit_button)
        tools.addStretch()
        root.addLayout(tools)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText(
            "Aplicar sugestões marcadas"
        )
        self.buttons.accepted.connect(self._accept_checked)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)

        self._load_rows()

    def accepted_candidates(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row, candidate in enumerate(self._candidates):
            item = self.table.item(row, 0)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                result.append(deepcopy(candidate))
        return result

    def _load_rows(self) -> None:
        self.table.setRowCount(0)
        for candidate in self._candidates:
            row = self.table.rowCount()
            self.table.insertRow(row)

            use_item = QTableWidgetItem()
            use_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            use_item.setCheckState(
                Qt.CheckState.Checked
                if bool(candidate.get("selected", False))
                else Qt.CheckState.Unchecked
            )
            if candidate.get("requires_configuration"):
                use_item.setToolTip(
                    "Esta sugestão precisa ser editada antes de ser aplicada."
                )
            self.table.setItem(row, 0, use_item)

            confidence = int(round(float(candidate.get("confidence", 0.0)) * 100))
            confidence_item = QTableWidgetItem(f"{confidence}%")
            confidence_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 1, confidence_item)

            self.table.setItem(
                row,
                2,
                QTableWidgetItem(candidate_source_label(candidate)),
            )
            self.table.setItem(
                row,
                3,
                QTableWidgetItem(str(candidate.get("field_id", ""))),
            )
            self.table.setItem(
                row,
                4,
                QTableWidgetItem(str(candidate.get("label", ""))),
            )
            self.table.setItem(
                row,
                5,
                QTableWidgetItem(self._candidate_type_label(candidate)),
            )
            preview_item = QTableWidgetItem(str(candidate.get("preview", "")))
            preview_item.setToolTip(str(candidate.get("preview", "")))
            self.table.setItem(row, 6, preview_item)

        self.table.resizeRowsToContents()
        self._update_summary()

    def _refresh_row(self, row: int) -> None:
        candidate = self._candidates[row]
        self.table.item(row, 3).setText(str(candidate.get("field_id", "")))
        self.table.item(row, 4).setText(str(candidate.get("label", "")))
        self.table.item(row, 5).setText(
            self._candidate_type_label(candidate)
        )
        use_item = self.table.item(row, 0)
        if candidate.get("requires_configuration"):
            use_item.setCheckState(Qt.CheckState.Unchecked)
            use_item.setToolTip("Esta sugestão precisa ser editada antes de ser aplicada.")
        else:
            use_item.setToolTip("")
        self._update_summary()

    def _candidate_type_label(self, candidate: dict[str, Any]) -> str:
        field_type = str(candidate.get("type", "text"))
        if field_type == "checkbox_group":
            if str(candidate.get("selection", "single")).casefold() == "multiple":
                return "Caixas independentes (múltipla seleção)"
            return "Grupo de escolha (uma opção)"
        return self.TYPE_LABELS.get(field_type, field_type)

    def _update_summary(self) -> None:
        high = sum(float(item.get("confidence", 0.0)) >= 0.80 for item in self._candidates)
        configurable = sum(bool(item.get("requires_configuration")) for item in self._candidates)
        text = f"{len(self._candidates)} sugestão(ões), {high} de alta confiança."
        if configurable:
            text += f" {configurable} precisa(m) de opções ou revisão manual."
        self.summary_label.setText(text)

    def _selected_row(self) -> int:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _edit_selected(self, *_args) -> None:
        row = self._selected_row()
        if row < 0:
            QMessageBox.information(
                self,
                "Selecionar sugestão",
                "Selecione uma linha para editar.",
            )
            return
        editor = _CandidateEditorDialog(self._candidates[row], self)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        self._candidates[row] = editor.candidate()
        self._refresh_row(row)
        if not self._candidates[row].get("requires_configuration"):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Checked)

    def _select_high_confidence(self) -> None:
        for row, candidate in enumerate(self._candidates):
            checked = (
                float(candidate.get("confidence", 0.0)) >= 0.80
                and not bool(candidate.get("requires_configuration"))
            )
            self.table.item(row, 0).setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )

    def _clear_selection(self) -> None:
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)

    def _accept_checked(self) -> None:
        accepted = self.accepted_candidates()
        if not accepted:
            QMessageBox.warning(
                self,
                "Nenhuma sugestão selecionada",
                "Marque pelo menos uma sugestão para aplicar.",
            )
            return

        ids: list[str] = []
        for candidate in accepted:
            if candidate.get("requires_configuration"):
                QMessageBox.warning(
                    self,
                    "Sugestão incompleta",
                    f"Edite '{candidate.get('label', candidate.get('field_id', 'campo'))}' "
                    "antes de aplicá-la.",
                )
                return
            if str(candidate.get("source", "")) == "checkbox_choice":
                ids.extend(
                    str(field.get("id", "")).strip()
                    for field in candidate.get("fields", []) or []
                )
            else:
                ids.append(str(candidate.get("field_id", "")).strip())

        invalid = sorted({field_id for field_id in ids if not VALID_FIELD_ID.match(field_id)})
        duplicates = sorted({field_id for field_id in ids if ids.count(field_id) > 1})
        if invalid:
            QMessageBox.warning(
                self,
                "ID inválido",
                "Corrija os seguintes IDs: " + ", ".join(invalid),
            )
            return
        if duplicates:
            QMessageBox.warning(
                self,
                "ID repetido",
                "Corrija os seguintes IDs repetidos: " + ", ".join(duplicates),
            )
            return
        self.accept()


class _CandidateEditorDialog(QDialog):
    def __init__(self, candidate: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self._candidate = deepcopy(candidate)
        self.setWindowTitle("Editar sugestão automática")
        self.resize(720, 560)

        root = QVBoxLayout(self)
        form = QFormLayout()

        self.id_input = QLineEdit(str(candidate.get("field_id", "")))
        self.id_input.setEnabled(str(candidate.get("source", "")) != "checkbox_choice")
        form.addRow("ID do campo", self.id_input)

        self.label_input = QLineEdit(str(candidate.get("label", "")))
        form.addRow("Rótulo", self.label_input)

        self.type_input = QComboBox()
        source = str(candidate.get("source", ""))
        allowed_types = [field_type for field_type in FIELD_TYPE_ORDER if field_type != "repeatable_table"]
        if source == "checkbox_choice":
            allowed_types = ["checkbox_group"]
        elif source == "repeatable_table":
            allowed_types = ["repeatable_table"]
        for field_type in allowed_types:
            self.type_input.addItem(
                AutomaticDetectionDialog.TYPE_LABELS.get(field_type, field_type),
                field_type,
            )
        current_type = str(candidate.get("type", "text"))
        index = self.type_input.findData(current_type)
        self.type_input.setCurrentIndex(max(0, index))
        self.type_input.currentIndexChanged.connect(self._refresh_options_state)
        form.addRow("Tipo", self.type_input)

        self.choice_layout_checkbox = QCheckBox(
            "Exibir como opções grandes de escolha única"
        )
        self.choice_layout_checkbox.setChecked(
            str(candidate.get("layout", "")) == "choice"
        )
        form.addRow("Apresentação", self.choice_layout_checkbox)

        root.addLayout(form)

        options_label = QLabel(
            "Opções — uma por linha. Use “Título curto => texto completo” quando necessário."
        )
        options_label.setWordWrap(True)
        root.addWidget(options_label)

        self.options_input = QPlainTextEdit()
        self.options_input.setMinimumHeight(220)
        self.options_input.setPlainText(_options_to_text(candidate.get("options", [])))
        root.addWidget(self.options_input, 1)

        preview_label = QLabel("Trecho encontrado no documento")
        root.addWidget(preview_label)
        preview = QPlainTextEdit(str(candidate.get("preview", "")))
        preview.setReadOnly(True)
        preview.setMaximumHeight(90)
        root.addWidget(preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._refresh_options_state()

    def candidate(self) -> dict[str, Any]:
        return deepcopy(self._candidate)

    def _refresh_options_state(self) -> None:
        field_type = str(self.type_input.currentData() or "text")
        is_dropdown = field_type == "dropdown"
        self.options_input.setEnabled(is_dropdown)
        self.choice_layout_checkbox.setEnabled(is_dropdown)

    def _validate_and_accept(self) -> None:
        field_id = self.id_input.text().strip()
        label = self.label_input.text().strip()
        field_type = str(self.type_input.currentData() or "text")

        if str(self._candidate.get("source", "")) != "checkbox_choice":
            if not VALID_FIELD_ID.match(field_id):
                QMessageBox.warning(
                    self,
                    "ID inválido",
                    "O ID deve começar com uma letra e usar apenas letras, números, ponto, hífen ou sublinhado.",
                )
                return
        if not label:
            QMessageBox.warning(self, "Rótulo ausente", "Informe um rótulo para o campo.")
            return

        options = _parse_options(self.options_input.toPlainText()) if field_type == "dropdown" else []
        if field_type == "dropdown" and len(options) < 2:
            QMessageBox.warning(
                self,
                "Opções insuficientes",
                "Informe pelo menos duas opções, uma por linha.",
            )
            return

        self._candidate["field_id"] = field_id
        self._candidate["label"] = label
        self._candidate["type"] = field_type
        self._candidate["options"] = options
        self._candidate["requires_configuration"] = False
        if field_type == "dropdown" and self.choice_layout_checkbox.isChecked():
            self._candidate["layout"] = "choice"
            self._candidate["layout_group"] = f"auto_choice_{field_id}"
        else:
            self._candidate.pop("layout", None)
            self._candidate.pop("layout_group", None)
        self.accept()


def _options_to_text(options: Any) -> str:
    lines: list[str] = []
    for option in compact_dropdown_options(options or []):
        if isinstance(option, dict):
            label = str(option.get("label", "")).strip()
            value = str(option.get("value", "")).strip()
            lines.append(value if label == value else f"{label} => {value}")
        else:
            lines.append(str(option))
    return "\n".join(lines)


def _parse_options(value: str) -> list[str | dict[str, str]]:
    options: list[str | dict[str, str]] = []
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=>" in line:
            label, output = [part.strip() for part in line.split("=>", 1)]
            if label and output:
                options.append({"label": label, "value": output})
            continue
        options.append(line)
    return compact_dropdown_options(options)
