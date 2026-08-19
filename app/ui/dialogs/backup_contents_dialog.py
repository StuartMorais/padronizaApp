from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.ui.widgets.context_help import HelpIconButton


class BackupContentsDialog(QDialog):
    def __init__(self, info: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Conteúdo do backup')
        self.resize(780, 520)

        metadata = info.get("metadata", {}) if isinstance(info, dict) else {}
        entries = info.get("entries", []) if isinstance(info, dict) else []

        summary = QLabel(
            f"Criado em: {metadata.get('created_at', 'Desconhecido')}    "
            f"Formato: {metadata.get('format', 'Desconhecido')}    "
            f"Arquivos: {len(entries)}"
        )
        summary.setWordWrap(True)

        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(['Arquivo', 'Tamanho'])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        table.setColumnWidth(0, 580)

        for entry in entries:
            row = table.rowCount()
            table.insertRow(row)
            table.setItem(row, 0, QTableWidgetItem(str(entry.get("name", ""))))
            table.setItem(row, 1, QTableWidgetItem(_format_size(int(entry.get("size", 0) or 0))))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        summary_row = QHBoxLayout()
        summary_row.addWidget(summary, 1)
        summary_row.addWidget(
            HelpIconButton(
                'Conteúdo do backup',
                (
                    '<p>Esta lista permite conferir o conteúdo do ZIP antes da restauração.</p>'
                    '<p>A visualização não altera os dados atuais. A substituição acontece '
                    'somente depois de confirmar a ação Restaurar backup ZIP.</p>'
                ),
            )
        )

        layout = QVBoxLayout(self)
        layout.addLayout(summary_row)
        layout.addWidget(table, 1)
        layout.addWidget(buttons)


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
