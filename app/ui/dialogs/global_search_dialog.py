from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.ui.widgets.context_help import HelpIconButton


class GlobalSearchDialog(QDialog):
    def __init__(self, records: list[dict[str, Any]], parent=None) -> None:
        super().__init__(parent)
        self.records = records
        self.selected_record: dict[str, Any] | None = None

        self.setWindowTitle('Pesquisa e comandos')
        self.resize(920, 560)
        self.setMinimumSize(760, 460)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('Pesquisar modelos, perfis, documentos, arquivos ou comandos…')
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._refresh)
        self.search_input.returnPressed.connect(self._accept_current)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Tipo', 'Nome', 'Detalhes', 'Local'])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 130)
        self.table.setColumnWidth(1, 260)
        self.table.setColumnWidth(2, 300)
        self.table.itemDoubleClicked.connect(lambda _item: self._accept_current())

        open_button = QPushButton('Abrir')
        open_button.setObjectName("primaryButton")
        open_button.clicked.connect(self._accept_current)
        close_button = QPushButton('Cancelar')
        close_button.clicked.connect(self.reject)

        button_row = QHBoxLayout()
        button_row.addWidget(QLabel('Dica: pressione Ctrl+K em qualquer tela para abrir esta janela.'))
        button_row.addWidget(
            HelpIconButton(
                'Pesquisa e comandos',
                (
                    '<p>Pesquisa modelos, perfis, documentos recentes, arquivos, '
                    'processos e comandos do aplicativo em uma única lista.</p>'
                    '<p>Digite parte do nome ou caminho. Pressione Enter ou clique duas '
                    'vezes para abrir o item selecionado.</p>'
                ),
            )
        )
        button_row.addStretch()
        button_row.addWidget(open_button)
        button_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search_input)
        layout.addWidget(self.table, 1)
        layout.addLayout(button_row)

        self._refresh()
        self.search_input.setFocus()

    def _refresh(self) -> None:
        needle = self.search_input.text().strip().casefold()
        self.table.setRowCount(0)

        for record in self.records:
            haystack = " ".join(str(value) for value in record.values()).casefold()
            if needle and needle not in haystack:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            location = str(record.get("path", ""))
            values = [
                str(record.get("kind", "")),
                str(record.get("name", "")),
                str(record.get("details", "")),
                Path(location).name if location else str(record.get("location", "")),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(str(record.get("path", value)))
                item.setData(Qt.ItemDataRole.UserRole, record)
                self.table.setItem(row, column, item)

        if self.table.rowCount():
            self.table.selectRow(0)

    def _accept_current(self) -> None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        record = item.data(Qt.ItemDataRole.UserRole) if item else None
        if isinstance(record, dict):
            self.selected_record = record
            self.accept()
