from __future__ import annotations

from copy import deepcopy
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.field_library import FieldLibraryStore
from app.widgets.context_help import HelpLabel


class FieldLibraryDialog(QDialog):
    def __init__(self, store: FieldLibraryStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.selected_fields: list[dict[str, Any]] = []

        self.setWindowTitle('Biblioteca de Campos')
        self.resize(900, 560)
        self.setMinimumSize(760, 480)

        self.group_list = QListWidget()
        self.group_list.setMinimumWidth(250)
        self.group_list.currentItemChanged.connect(self._show_group)

        self.description = QLabel()
        self.description.setWordWrap(True)
        self.description.setObjectName("mutedText")

        self.preview = QTableWidget(0, 4)
        self.preview.setHorizontalHeaderLabels(['ID do campo', 'Rótulo', 'Tipo', 'Seção'])
        self.preview.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.preview.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.preview.horizontalHeader().setStretchLastSection(True)
        self.preview.setColumnWidth(0, 220)
        self.preview.setColumnWidth(1, 210)
        self.preview.setColumnWidth(2, 100)

        self.delete_button = QPushButton('Excluir grupo personalizado')
        self.delete_button.clicked.connect(self._delete_selected)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Inserir grupo')
        buttons.accepted.connect(self._accept_group)
        buttons.rejected.connect(self.reject)

        right = QVBoxLayout()
        right.addWidget(self.description)
        right.addWidget(self.preview, 1)
        right.addWidget(self.delete_button)

        content = QHBoxLayout()
        content.addWidget(self.group_list)
        content.addLayout(right, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(
            HelpLabel(
                'Escolha um grupo reutilizável de campos',
                'Biblioteca de Campos',
                (
                    '<p>Um grupo insere vários campos relacionados de uma só vez, como '
                    'empresa, endereço ou assinatura.</p>'
                    '<p>Grupos integrados não podem ser excluídos. Grupos personalizados '
                    'são criados no Editor de Modelo a partir dos campos selecionados.</p>'
                ),
            )
        )
        layout.addLayout(content, 1)
        layout.addWidget(buttons)

        self._reload()

    def _reload(self) -> None:
        self.group_list.clear()
        for group_data in self.store.list_groups():
            item = QListWidgetItem(str(group_data.get("name", 'Grupo de campos')))
            item.setData(Qt.ItemDataRole.UserRole, group_data)
            self.group_list.addItem(item)
        if self.group_list.count():
            self.group_list.setCurrentRow(0)

    def _show_group(self, current: QListWidgetItem | None, _previous=None) -> None:
        group_data = current.data(Qt.ItemDataRole.UserRole) if current else None
        group_data = group_data if isinstance(group_data, dict) else {}
        self.description.setText(str(group_data.get("description", "")))
        self.delete_button.setEnabled(bool(group_data and not group_data.get("builtin", False)))
        self.preview.setRowCount(0)
        for field in group_data.get("fields", []):
            if not isinstance(field, dict):
                continue
            row = self.preview.rowCount()
            self.preview.insertRow(row)
            values = [
                str(field.get("id", "")),
                str(field.get("label", "")),
                str(field.get("type", "text")),
                str(field.get("section", "")),
            ]
            for column, value in enumerate(values):
                self.preview.setItem(row, column, QTableWidgetItem(value))

    def _accept_group(self) -> None:
        item = self.group_list.currentItem()
        group_data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(group_data, dict):
            return
        self.selected_fields = deepcopy(
            [
                field
                for field in group_data.get("fields", [])
                if isinstance(field, dict)
            ]
        )
        if not self.selected_fields:
            QMessageBox.warning(self, 'Grupo vazio', 'Este grupo não possui campos.')
            return
        self.accept()

    def _delete_selected(self) -> None:
        item = self.group_list.currentItem()
        group_data = item.data(Qt.ItemDataRole.UserRole) if item else None
        if not isinstance(group_data, dict) or group_data.get("builtin", False):
            return
        answer = QMessageBox.question(
            self,
            'Excluir grupo de campos',
            f"Excluir '{group_data.get('name', '')}' da Biblioteca de Campos?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_group(str(group_data.get("id", "")))
        self._reload()
