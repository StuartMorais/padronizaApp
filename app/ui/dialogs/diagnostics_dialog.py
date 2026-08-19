from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets.context_help import HelpLabel


class DiagnosticsDialog(QDialog):
    """Human-readable diagnostics with a structured issue navigator.

    ``report_text`` remains supported for callers that only have the legacy
    textual report. When the structured ``report`` is provided, problems are
    grouped in a table and field issues can jump back to the editor.
    """

    def __init__(
        self,
        title: str,
        report_text: str,
        parent=None,
        *,
        report: dict[str, Any] | None = None,
        on_field_activated: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(860, 650)
        self._report = report or {}
        self._on_field_activated = on_field_activated

        tabs = QTabWidget()
        issues = [
            item
            for item in self._report.get("issues", [])
            if isinstance(item, dict)
        ]
        if issues:
            tabs.addTab(self._build_issues_page(issues), "Problemas")

        report_editor = QPlainTextEdit()
        report_editor.setReadOnly(True)
        report_editor.setPlainText(report_text)
        tabs.addTab(report_editor, "Relatório completo")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(
            HelpLabel(
                "Relatório de diagnóstico",
                "Como interpretar o diagnóstico",
                (
                    "<p>O diagnóstico procura problemas no DOCX, nos marcadores, nos "
                    "campos e nas regras do modelo.</p>"
                    "<p><b>Erros</b> precisam ser corrigidos antes da geração. "
                    "<b>Avisos</b> não bloqueiam o modelo, mas merecem revisão.</p>"
                    "<p>Quando um problema aponta para um campo, dê dois cliques nele "
                    "para voltar diretamente ao campo no editor.</p>"
                ),
            )
        )
        if self._report:
            layout.addWidget(
                QLabel(
                    f"Erros: {int(self._report.get('blocking_count', 0) or 0)}  •  "
                    f"Avisos: {int(self._report.get('warning_count', 0) or 0)}"
                )
            )
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)

    def _build_issues_page(self, issues: list[dict[str, Any]]) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        self.issue_tree = QTreeWidget()
        self.issue_tree.setRootIsDecorated(False)
        self.issue_tree.setAlternatingRowColors(True)
        self.issue_tree.setColumnCount(4)
        self.issue_tree.setHeaderLabels(("Nível", "Problema", "Campo", "Local"))
        header = self.issue_tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        for issue in issues:
            severity = str(issue.get("severity", "warning")).casefold()
            label = "Erro" if severity == "error" else "Aviso"
            field_id = str(issue.get("field_id", "") or "")
            locations = [str(item) for item in issue.get("locations", []) if str(item)]
            message = str(issue.get("message", "") or issue.get("code", "Problema"))
            item = QTreeWidgetItem((label, message, field_id, ", ".join(locations)))
            item.setData(0, Qt.ItemDataRole.UserRole, issue)
            if field_id and self._on_field_activated is not None:
                item.setToolTip(1, "Dê dois cliques para abrir este campo no editor.")
            self.issue_tree.addTopLevelItem(item)

        self.issue_details = QPlainTextEdit()
        self.issue_details.setReadOnly(True)
        self.issue_details.setMaximumHeight(145)
        self.issue_details.setPlaceholderText("Selecione um problema para ver os detalhes.")

        self.issue_tree.currentItemChanged.connect(self._show_issue_details)
        self.issue_tree.itemDoubleClicked.connect(self._activate_issue)
        if self.issue_tree.topLevelItemCount():
            self.issue_tree.setCurrentItem(self.issue_tree.topLevelItem(0))

        layout.addWidget(self.issue_tree, 1)
        layout.addWidget(self.issue_details)
        return page

    def _show_issue_details(self, current: QTreeWidgetItem | None, _previous) -> None:
        if current is None:
            self.issue_details.clear()
            return
        issue = current.data(0, Qt.ItemDataRole.UserRole) or {}
        details = [str(issue.get("message", ""))]
        code = str(issue.get("code", "") or "")
        field_id = str(issue.get("field_id", "") or "")
        locations = [str(item) for item in issue.get("locations", []) if str(item)]
        if code:
            details.append(f"Código: {code}")
        if field_id:
            details.append(f"Campo: {field_id}")
        if locations:
            details.append("Local: " + ", ".join(locations))
        if issue.get("safe_fix"):
            details.append("Este problema possui uma correção segura identificada pelo diagnóstico.")
        self.issue_details.setPlainText("\n".join(part for part in details if part))

    def _activate_issue(self, item: QTreeWidgetItem, _column: int) -> None:
        if self._on_field_activated is None:
            return
        issue = item.data(0, Qt.ItemDataRole.UserRole) or {}
        field_id = str(issue.get("field_id", "") or "").strip()
        if not field_id:
            return
        self.accept()
        self._on_field_activated(field_id)
