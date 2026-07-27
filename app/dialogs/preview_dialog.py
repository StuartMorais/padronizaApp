from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.widgets.context_help import HelpIconButton


class PreviewDialog(QDialog):
    def __init__(
        self,
        *,
        template_name: str,
        values: dict[str, Any],
        labels: dict[str, str],
        output_path: Path,
        diagnostics_summary: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle('Revisar documento')
        self.resize(850, 650)

        title = QLabel(f"Revisão — {template_name}")
        title.setObjectName("pageTitle")

        details = QFormLayout()
        output_label = QLabel(str(output_path))
        output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        output_label.setWordWrap(True)
        details.addRow('Saída:', output_label)

        if diagnostics_summary:
            diagnostics = QLabel(diagnostics_summary)
            diagnostics.setWordWrap(True)
            diagnostics.setObjectName("mutedText")
            details.addRow('Verificação do modelo:', diagnostics)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(['Campo', 'Conteúdo que será inserido'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        for field_id, value in values.items():
            row = table.rowCount()
            table.insertRow(row)
            label = labels.get(field_id, field_id)
            if isinstance(value, bool):
                rendered = '☑ Selecionado' if value else '☐ Não selecionado'
            else:
                rendered = str(value or "")

            label_item = QTableWidgetItem(label)
            label_item.setToolTip(field_id)
            value_item = QTableWidgetItem(rendered)
            value_item.setToolTip(rendered)
            table.setItem(row, 0, label_item)
            table.setItem(row, 1, value_item)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText('Gerar')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        title_row = QHBoxLayout()
        title_row.addWidget(title)
        title_row.addWidget(
            HelpIconButton(
                'Revisão antes da geração',
                (
                    '<p>Confira o caminho de saída e os conteúdos que serão inseridos '
                    'no documento.</p>'
                    '<p>Cancelar retorna ao formulário sem gerar. O botão Gerar cria '
                    'o arquivo usando exatamente os dados apresentados nesta revisão.</p>'
                ),
            )
        )
        title_row.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(title_row)
        layout.addLayout(details)
        layout.addWidget(table, 1)
        layout.addWidget(buttons)
