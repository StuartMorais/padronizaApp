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
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .scanner import confidence_band


class ScanReviewDialog(QDialog):
    """Padroniza-style review of detected checklist rows before import."""

    def __init__(self, candidates: list[dict[str, Any]], parent=None, *, report: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self._candidates = [deepcopy(item) for item in candidates]
        self._report = dict(report or {})
        self.setWindowTitle("Confira os itens encontrados")
        self.resize(1220, 760)
        self.setMinimumSize(900, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Confira o que o scanner encontrou")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        description = QLabel(
            "Itens marcados como Identificado já vêm selecionados. Confira principalmente os itens "
            "marcados como Confira ou Possível item antes de importar o checklist."
        )
        description.setWordWrap(True)
        description.setObjectName("mutedText")
        root.addWidget(description)

        self.summary = QLabel()
        self.summary.setObjectName("statusBadge")
        root.addWidget(self.summary)

        filters = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Pesquisar item, documento ou normativo…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._apply_filters)
        filters.addWidget(self.search_input, 1)

        self.review_filter = QComboBox()
        self.review_filter.addItem("Todos", "all")
        self.review_filter.addItem("Identificados", "Identificado")
        self.review_filter.addItem("Confira", "Confira")
        self.review_filter.addItem("Possíveis itens", "Possível item")
        self.review_filter.currentIndexChanged.connect(self._apply_filters)
        filters.addWidget(self.review_filter)

        self.technical_button = QPushButton("Detalhes técnicos")
        self.technical_button.setCheckable(True)
        self.technical_button.toggled.connect(self._toggle_technical)
        filters.addWidget(self.technical_button)
        root.addLayout(filters)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "Usar", "Status", "Item", "Documento / informação", "Normativo", "Página", "Origem"
        ])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._update_details)
        header = self.table.horizontalHeader()
        for column in (0, 1, 2, 5, 6):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnHidden(6, True)
        root.addWidget(self.table, 1)

        context_title = QLabel("Onde isso aparece no documento?")
        context_title.setObjectName("mutedText")
        root.addWidget(context_title)
        self.context = QLabel()
        self.context.setWordWrap(True)
        self.context.setMinimumHeight(46)
        root.addWidget(self.context)

        evidence_title = QLabel("Por que o scanner identificou este item?")
        evidence_title.setObjectName("mutedText")
        root.addWidget(evidence_title)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(125)
        root.addWidget(self.details)

        tools = QHBoxLayout()
        use_recommended = QPushButton("Usar recomendados")
        use_recommended.clicked.connect(self._select_recommended)
        tools.addWidget(use_recommended)
        select_visible = QPushButton("Usar exibidos")
        select_visible.clicked.connect(lambda: self._set_visible(True))
        tools.addWidget(select_visible)
        clear = QPushButton("Não usar nenhum")
        clear.clicked.connect(lambda: self._set_visible(False))
        tools.addWidget(clear)
        tools.addStretch()
        root.addLayout(tools)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Importar itens marcados")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._load()

    def _load(self) -> None:
        self.table.setRowCount(len(self._candidates))
        for row, candidate in enumerate(self._candidates):
            use = QTableWidgetItem("")
            use.setFlags((use.flags() | Qt.ItemFlag.ItemIsUserCheckable) & ~Qt.ItemFlag.ItemIsEditable)
            use.setCheckState(Qt.CheckState.Checked if candidate.get("selected") else Qt.CheckState.Unchecked)
            self.table.setItem(row, 0, use)

            confidence = float(candidate.get("confidence", 0.0) or 0.0)
            status = QTableWidgetItem(str(candidate.get("confidence_band") or confidence_band(confidence)))
            status.setFlags(status.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, status)

            number = QTableWidgetItem(str(candidate.get("number") or ""))
            self.table.setItem(row, 2, number)
            self.table.setItem(row, 3, QTableWidgetItem(str(candidate.get("documento") or "")))
            self.table.setItem(row, 4, QTableWidgetItem(str(candidate.get("normativo") or "")))
            page = QTableWidgetItem(str(candidate.get("source_page") or "—"))
            page.setFlags(page.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 5, page)
            origin = QTableWidgetItem(str(candidate.get("source") or ""))
            origin.setFlags(origin.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 6, origin)
        self.table.resizeRowsToContents()
        self._update_summary()
        if self.table.rowCount():
            self.table.selectRow(0)

    def _toggle_technical(self, enabled: bool) -> None:
        self.table.setColumnHidden(6, not enabled)

    def _apply_filters(self) -> None:
        query = self.search_input.text().strip().casefold()
        band = str(self.review_filter.currentData() or "all")
        for row, candidate in enumerate(self._candidates):
            haystack = " ".join(str(candidate.get(key) or "") for key in ("number", "documento", "normativo")).casefold()
            candidate_band = str(candidate.get("confidence_band") or confidence_band(float(candidate.get("confidence", 0.0) or 0.0)))
            visible = (not query or query in haystack) and (band == "all" or band == candidate_band)
            self.table.setRowHidden(row, not visible)

    def _update_details(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.context.clear()
            self.details.clear()
            return
        candidate = self._candidates[rows[0].row()]
        context = str(candidate.get("source_context") or candidate.get("documento") or "")
        page = int(candidate.get("source_page") or 0)
        self.context.setText((f"Página {page}: " if page else "") + context)
        evidence = [str(item) for item in candidate.get("evidence", []) if str(item)]
        reasons = [str(item) for item in candidate.get("auto_apply_reasons", []) if str(item)]
        dimensions = dict(candidate.get("confidence_dimensions") or {})
        lines = [*evidence]
        if reasons:
            lines.extend(["", "Motivos para revisão:", *[f"• {value}" for value in reasons]])
        if dimensions:
            lines.extend(["", "Evidências técnicas:"])
            lines.extend(f"• {key}: {float(value):.0%}" for key, value in dimensions.items())
        self.details.setPlainText("\n".join(lines))

    def _select_recommended(self) -> None:
        for row, candidate in enumerate(self._candidates):
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked if candidate.get("auto_apply_eligible") else Qt.CheckState.Unchecked)
        self._update_summary()

    def _set_visible(self, checked: bool) -> None:
        for row in range(self.table.rowCount()):
            if self.table.isRowHidden(row):
                continue
            item = self.table.item(row, 0)
            if item is not None:
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._update_summary()

    def _update_summary(self) -> None:
        selected = sum(self.table.item(row, 0) is not None and self.table.item(row, 0).checkState() == Qt.CheckState.Checked for row in range(self.table.rowCount()))
        review = sum(str(item.get("confidence_band")) != "Identificado" for item in self._candidates)
        self.summary.setText(f"{len(self._candidates)} item(ns) encontrados · {selected} marcado(s) · {review} para conferir")

    def reviewed_candidates(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row, candidate in enumerate(self._candidates):
            reviewed = deepcopy(candidate)
            reviewed["number"] = self.table.item(row, 2).text().strip() if self.table.item(row, 2) else ""
            reviewed["documento"] = self.table.item(row, 3).text().strip() if self.table.item(row, 3) else ""
            reviewed["normativo"] = self.table.item(row, 4).text().strip() if self.table.item(row, 4) else ""
            use = self.table.item(row, 0)
            accepted = bool(use is not None and use.checkState() == Qt.CheckState.Checked)
            reviewed["reviewed_by_user"] = True
            reviewed["accepted_by_user"] = accepted
            reviewed["selected"] = accepted
            result.append(reviewed)
        return result


class ScanDiagnosticsDialog(QDialog):
    def __init__(self, report: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Diagnóstico do scanner")
        self.resize(900, 620)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Diagnóstico do documento")
        title.setObjectName("pageTitle")
        root.addWidget(title)
        issues = list(report.get("issues") or [])
        blocking = int(report.get("blocking_issue_count") or 0)
        summary = QLabel(
            f"Scanner V{report.get('scanner_version', '?')} · {report.get('page_count', 0)} página(s) · "
            f"{report.get('candidate_count', 0)} item(ns) · {blocking} erro(s) bloqueante(s)"
        )
        summary.setObjectName("statusBadge")
        root.addWidget(summary)

        self.table = QTableWidget(len(issues), 5)
        self.table.setHorizontalHeaderLabels(["Severidade", "Código", "Item", "Página", "Mensagem"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        header = self.table.horizontalHeader()
        for col in (0, 1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for row, issue in enumerate(issues):
            values = [issue.get("severity"), issue.get("code"), issue.get("item_number"), issue.get("page"), issue.get("message")]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value or ""))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        root.addWidget(self.table, 1)

        warnings = [str(item) for item in report.get("warnings", []) if str(item)]
        warning_text = QPlainTextEdit()
        warning_text.setReadOnly(True)
        warning_text.setMaximumHeight(130)
        warning_text.setPlainText("\n".join(f"• {item}" for item in warnings) if warnings else "Nenhum aviso adicional.")
        root.addWidget(warning_text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        root.addWidget(buttons)


class ScanReportDialog(QDialog):
    def __init__(self, report: dict[str, Any], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Relatório técnico do scanner")
        self.resize(860, 650)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        title = QLabel("Relatório técnico")
        title.setObjectName("pageTitle")
        root.addWidget(title)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        lines = [
            f"Scanner: V{report.get('scanner_version', '?')}",
            f"Fonte: {report.get('source_kind', '')}",
            f"Estrutura: {report.get('structure_kind', '')}",
            f"Páginas: {report.get('page_count', 0)}",
            f"Páginas com cabeçalho da grade: {report.get('table_header_pages', 0)}",
            f"Itens encontrados: {report.get('candidate_count', 0)}",
            f"Pré-selecionados: {report.get('selected_count', 0)}",
            f"Para revisão: {report.get('review_count', 0)}",
            "",
            "Seções:",
            *[f"• {item}" for item in report.get("sections", [])],
            "",
            "Metadados extraídos:",
            *[f"• {key}: {value}" for key, value in dict(report.get("extracted_metadata") or {}).items()],
        ]
        if report.get("warnings"):
            lines.extend(["", "Avisos:", *[f"• {item}" for item in report.get("warnings", [])]])
        text.setPlainText("\n".join(lines))
        root.addWidget(text, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).clicked.connect(self.accept)
        root.addWidget(buttons)
