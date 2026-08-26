from __future__ import annotations

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
)

from app.document.detection.candidates import candidate_source_label
from app.document.understanding.semantic import candidate_explanation, confidence_band
from app.domain.field_ids import VALID_FIELD_ID
from app.domain.field_metadata import compact_dropdown_options
from app.domain.field_types import FIELD_TYPE_ORDER


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
        *,
        scan_report: dict[str, Any] | None = None,
        known_field_count: int = 0,
    ) -> None:
        super().__init__(parent)
        self._candidates = [deepcopy(item) for item in candidates]
        self._scan_report = dict(scan_report or {})
        self._known_field_count = max(0, int(known_field_count or 0))
        self.setWindowTitle("Revisar campos encontrados")
        self.resize(1180, 720)
        self.setMinimumSize(820, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Revise os campos adicionais encontrados")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        known_prefix = (
            f"O Padroniza já reconheceu {self._known_field_count} campo(s) por tags ou controles. "
            if self._known_field_count
            else ""
        )
        description = QLabel(
            known_prefix
            + "Abaixo estão áreas adicionais encontradas por estrutura, texto, posição, tabelas e "
            "consistência visual. Sugestões fortes podem vir marcadas; interpretações ambíguas ficam "
            "desmarcadas para confirmação. Somente as opções marcadas serão inseridas no DOCX."
        )
        description.setWordWrap(True)
        root.addWidget(description)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.structure_summary_label = QLabel(self._format_structure_summary())
        self.structure_summary_label.setWordWrap(True)
        self.structure_summary_label.setObjectName("mutedText")
        root.addWidget(self.structure_summary_label)

        filters = QHBoxLayout()
        filters.setSpacing(7)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Pesquisar por ID, rótulo, origem ou trecho…")
        self.search_input.setClearButtonEnabled(True)
        filters.addWidget(self.search_input, 1)

        self.confidence_filter = QComboBox()
        self.confidence_filter.addItem("Todas as confianças", "all")
        self.confidence_filter.addItem("Alta confiança", "high")
        self.confidence_filter.addItem("Média confiança", "medium")
        self.confidence_filter.addItem("Baixa confiança", "low")
        filters.addWidget(self.confidence_filter)

        self.review_filter = QComboBox()
        self.review_filter.addItem("Todos os estados", "all")
        self.review_filter.addItem("Prontas para aplicar", "ready")
        self.review_filter.addItem("Revisão recomendada", "recommended")
        self.review_filter.addItem("Revisão necessária", "required")
        filters.addWidget(self.review_filter)

        self.type_filter = QComboBox()
        self.type_filter.addItem("Todos os tipos", "all")
        for field_type in FIELD_TYPE_ORDER:
            self.type_filter.addItem(
                self.TYPE_LABELS.get(field_type, field_type),
                field_type,
            )
        self.type_filter.addItem("Grupo de caixas", "checkbox_group")
        filters.addWidget(self.type_filter)
        root.addLayout(filters)

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
        self.table.itemSelectionChanged.connect(self._update_details)
        self.search_input.textChanged.connect(self._apply_filters)
        self.confidence_filter.currentIndexChanged.connect(self._apply_filters)
        self.review_filter.currentIndexChanged.connect(self._apply_filters)
        self.type_filter.currentIndexChanged.connect(self._apply_filters)
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

        details_title = QLabel("Por que esta sugestão foi criada?")
        details_title.setObjectName("mutedText")
        root.addWidget(details_title)
        self.details_text = QPlainTextEdit()
        self.details_text.setReadOnly(True)
        self.details_text.setMaximumHeight(118)
        self.details_text.setPlaceholderText(
            "Selecione uma sugestão para ver confiança, contexto e motivos de revisão."
        )
        root.addWidget(self.details_text)

        tools = QHBoxLayout()
        self.high_confidence_button = QPushButton("Marcar recomendadas")
        self.high_confidence_button.clicked.connect(self._select_high_confidence)
        tools.addWidget(self.high_confidence_button)

        self.select_visible_button = QPushButton("Marcar visíveis")
        self.select_visible_button.clicked.connect(self._select_visible)
        tools.addWidget(self.select_visible_button)

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
                approved = deepcopy(candidate)
                approved["reviewed_by_user"] = True
                result.append(approved)
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
            selection_reasons = [
                str(value)
                for value in candidate.get("auto_apply_reasons", []) or []
                if str(value).strip()
            ]
            if candidate.get("requires_configuration"):
                use_item.setToolTip(
                    "Esta sugestão precisa ser editada antes de ser aplicada."
                )
            elif selection_reasons:
                use_item.setToolTip(
                    "Não foi pré-marcada automaticamente:\n" + "\n".join(selection_reasons)
                )
            elif candidate.get("auto_apply_eligible") is True:
                use_item.setToolTip(
                    "Sinais estruturais consistentes: pré-marcada para aplicação."
                )
            self.table.setItem(row, 0, use_item)

            confidence_value = float(candidate.get("confidence", 0.0))
            confidence = int(round(confidence_value * 100))
            band = str(candidate.get("confidence_band", "")) or confidence_band(confidence_value)
            band_label = {"high": "Alta", "medium": "Média", "low": "Baixa"}.get(band, "")
            confidence_item = QTableWidgetItem(f"{band_label} {confidence}%".strip())
            confidence_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            explanation = candidate_explanation(candidate)
            if explanation:
                confidence_item.setToolTip(explanation)
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
        self._apply_filters()
        self._update_summary()
        if self.table.rowCount() and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self._update_details()

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
            selection_reasons = [
                str(value)
                for value in candidate.get("auto_apply_reasons", []) or []
                if str(value).strip()
            ]
            use_item.setToolTip(
                "Não foi pré-marcada automaticamente:\n" + "\n".join(selection_reasons)
                if selection_reasons
                else ""
            )
        self._refresh_candidate_review_state(candidate)
        self._apply_filters()
        self._update_summary()
        self._update_details()

    def _candidate_type_label(self, candidate: dict[str, Any]) -> str:
        field_type = str(candidate.get("type", "text"))
        if field_type == "checkbox_group":
            if str(candidate.get("selection", "single")).casefold() == "multiple":
                return "Caixas independentes (múltipla seleção)"
            return "Grupo de escolha (uma opção)"
        return self.TYPE_LABELS.get(field_type, field_type)

    def _update_summary(self) -> None:
        bands = {"high": 0, "medium": 0, "low": 0}
        priorities = {"ready": 0, "recommended": 0, "required": 0}
        checked = 0
        auto_eligible = 0
        visible = 0
        for row, item in enumerate(self._candidates):
            band = str(item.get("confidence_band", "")) or confidence_band(float(item.get("confidence", 0.0)))
            if band in bands:
                bands[band] += 1
            priority = str(item.get("review_priority", "")) or self._review_priority(item)
            if priority in priorities:
                priorities[priority] += 1
            if item.get("auto_apply_eligible") is True:
                auto_eligible += 1
            use_item = self.table.item(row, 0)
            if use_item is not None and use_item.checkState() == Qt.CheckState.Checked:
                checked += 1
            if row < self.table.rowCount() and not self.table.isRowHidden(row):
                visible += 1
        prefix = (
            f"{self._known_field_count} campo(s) já reconhecido(s). "
            if self._known_field_count
            else ""
        )
        text = (
            prefix
            + f"{len(self._candidates)} sugestão(ões) adicional(is): "
            f"{bands['high']} alta, {bands['medium']} média e {bands['low']} baixa confiança. "
            f"{priorities['required']} exigem revisão e {priorities['recommended']} recomendam revisão. "
            f"{auto_eligible} passaram pela política de pré-aplicação. "
            f"Exibindo {visible}; {checked} marcada(s) para aplicar."
        )
        self.summary_label.setText(text)

    def _apply_filters(self, *_args) -> None:
        query = self.search_input.text().strip().casefold() if hasattr(self, "search_input") else ""
        confidence = str(self.confidence_filter.currentData() or "all") if hasattr(self, "confidence_filter") else "all"
        review = str(self.review_filter.currentData() or "all") if hasattr(self, "review_filter") else "all"
        field_type = str(self.type_filter.currentData() or "all") if hasattr(self, "type_filter") else "all"

        for row, candidate in enumerate(self._candidates):
            band = str(candidate.get("confidence_band", "")) or confidence_band(float(candidate.get("confidence", 0.0)))
            priority = str(candidate.get("review_priority", "")) or self._review_priority(candidate)
            candidate_type = str(candidate.get("type", "text"))
            haystack = " ".join(
                (
                    str(candidate.get("field_id", "")),
                    str(candidate.get("label", "")),
                    str(candidate.get("preview", "")),
                    candidate_source_label(candidate),
                )
            ).casefold()
            visible = (
                (not query or query in haystack)
                and (confidence == "all" or confidence == band)
                and (review == "all" or review == priority)
                and (field_type == "all" or field_type == candidate_type)
            )
            self.table.setRowHidden(row, not visible)
        self._update_summary()

    @staticmethod
    def _review_priority(candidate: dict[str, Any]) -> str:
        if candidate.get("requires_configuration"):
            return "required"
        band = str(candidate.get("confidence_band", "")) or confidence_band(float(candidate.get("confidence", 0.0)))
        if band == "low":
            return "required"
        if band == "medium" or candidate.get("review_reasons"):
            return "recommended"
        return "ready"

    @classmethod
    def _refresh_candidate_review_state(cls, candidate: dict[str, Any]) -> None:
        priority = cls._review_priority(candidate)
        candidate["review_priority"] = priority
        candidate["needs_review"] = priority != "ready"
        candidate["review_summary"] = {
            "required": "Revisão necessária antes de aplicar.",
            "recommended": "Revisão rápida recomendada.",
            "ready": "Sugestão consistente com os sinais encontrados.",
        }[priority]

    def _update_details(self) -> None:
        if not hasattr(self, "details_text"):
            return
        row = self._selected_row()
        if row < 0 or row >= len(self._candidates):
            self.details_text.clear()
            return
        candidate = self._candidates[row]
        confidence = int(round(float(candidate.get("confidence", 0.0)) * 100))
        priority = str(candidate.get("review_priority", "")) or self._review_priority(candidate)
        priority_label = {
            "ready": "Pronta para aplicar",
            "recommended": "Revisão recomendada",
            "required": "Revisão necessária",
        }.get(priority, priority)
        location = candidate.get("location", {}) or {}
        lines = [
            f"{candidate.get('label', candidate.get('field_id', 'Campo'))} — {confidence}% — {priority_label}",
            f"Origem: {candidate_source_label(candidate)}",
        ]
        dimensions = candidate.get("confidence_dimensions", {}) or {}
        if isinstance(dimensions, dict) and dimensions:
            labels = {"structure": "estrutura", "fillable": "preenchível", "label": "rótulo", "type": "tipo"}
            parts = []
            for key in ("structure", "fillable", "label", "type"):
                if key not in dimensions:
                    continue
                try:
                    parts.append(f"{labels[key]} {int(round(float(dimensions[key]) * 100))}%")
                except (TypeError, ValueError):
                    pass
            if parts:
                lines.append("Confiança por dimensão: " + " · ".join(parts))
        semantic_label = str(candidate.get("semantic_label_suggestion", "")).strip()
        if semantic_label and semantic_label != str(candidate.get("label", "")).strip():
            semantic_confidence = int(round(float(candidate.get("semantic_label_confidence", 0.0)) * 100))
            lines.append(f"Rótulo contextual sugerido: {semantic_label} ({semantic_confidence}%)")
        if location:
            location_bits = [f"{key}={value}" for key, value in location.items() if value not in (None, "", [], {})]
            if location_bits:
                lines.append("Local: " + ", ".join(location_bits))
        reasons = [str(value) for value in candidate.get("review_reasons", []) or [] if str(value).strip()]
        if reasons:
            lines.append("Revisar porque: " + " • ".join(reasons))
        auto_reasons = [
            str(value)
            for value in candidate.get("auto_apply_reasons", []) or []
            if str(value).strip()
        ]
        if candidate.get("auto_apply_eligible") is True:
            lines.append("Pré-aplicação: elegível; os sinais mínimos foram satisfeitos.")
        elif auto_reasons:
            lines.append("Pré-aplicação: exige confirmação — " + " • ".join(auto_reasons))
        explanation = candidate_explanation(candidate)
        if explanation:
            lines.append("Sinais usados:\n" + explanation)
        self.details_text.setPlainText("\n".join(lines))

    def _format_structure_summary(self) -> str:
        report = self._scan_report
        if not report:
            return ""
        sections = len(report.get("sections", []) or [])
        tables = report.get("tables", []) or []
        kinds: dict[str, int] = {}
        for table in tables:
            if not isinstance(table, dict):
                continue
            kind = str(table.get("kind", "unknown"))
            kinds[kind] = kinds.get(kind, 0) + 1
        kind_text = ", ".join(f"{key}: {value}" for key, value in sorted(kinds.items()))
        protected = int(report.get("protected_tables", 0) or 0)
        ambiguous = int(report.get("ignored_ambiguous_tables", 0) or 0)
        version = int(report.get("scanner_version", 0) or 0)
        suffix = []
        if protected:
            suffix.append(f"{protected} tabela(s) manualmente protegida(s)")
        if ambiguous:
            suffix.append(f"{ambiguous} tabela(s) ambígua(s) não achatada(s)")
        extra = (" · " + " · ".join(suffix)) if suffix else ""
        return f"Estrutura v{version}: {sections} seção(ões), {len(tables)} tabela(s) ({kind_text or 'sem tabelas'}){extra}."

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
            checked = bool(candidate.get("selected", False)) and not bool(candidate.get("requires_configuration"))
            self.table.item(row, 0).setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            )
        self._update_summary()

    def _select_visible(self) -> None:
        for row, candidate in enumerate(self._candidates):
            if self.table.isRowHidden(row) or candidate.get("requires_configuration"):
                continue
            self.table.item(row, 0).setCheckState(Qt.CheckState.Checked)
        self._update_summary()

    def _clear_selection(self) -> None:
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
        self._update_summary()

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

        self.section_input = QLineEdit(str(candidate.get("section", "")))
        self.section_input.setPlaceholderText("Seção do formulário (opcional)")
        form.addRow("Seção", self.section_input)

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
        section = self.section_input.text().strip()
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
        if section:
            self._candidate["section"] = section
            self._candidate["section_source"] = "manual_review"
        else:
            self._candidate.pop("section", None)
            self._candidate.pop("section_source", None)
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
