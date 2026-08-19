from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.repositories.local_data import LocalDataStore
from app.ui.widgets.context_help import HelpLabel
from app.ui.widgets.empty_state import EmptyState
from app.ui.widgets.toast import show_toast


class ProfileManagerDialog(QDialog):
    def __init__(self, store: LocalDataStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle('Gerenciar perfis de preenchimento')
        self.resize(760, 480)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Nome', 'Categoria', 'Campos salvos', 'Atualizado em'])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self.empty_state = EmptyState(
            'Nenhum perfil salvo',
            (
                'Crie um perfil na página Gerar usando os dados preenchidos. '
                'Ele poderá ser aplicado em novos documentos.'
            ),
            icon='♙',
        )
        self.empty_state.setMinimumHeight(180)

        self.delete_button = QPushButton('Excluir perfil selecionado')
        self.delete_button.clicked.connect(self._delete_selected)

        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(
            HelpLabel(
                'Perfis salvos',
                'Como funcionam os perfis',
                (
                    '<p>Perfis guardam dados reutilizáveis, como informações da empresa e '
                    'do representante.</p>'
                    '<p>Excluir um perfil não altera documentos já gerados nem os modelos. '
                    'Novos perfis são criados a partir da página Gerar.</p>'
                ),
            )
        )
        layout.addWidget(self.empty_state, 1)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.delete_button)
        layout.addWidget(close_buttons)

        self._reload()

    def _reload(self) -> None:
        self.table.setRowCount(0)
        for profile in self.store.list_profiles():
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(str(profile.get("name", "")))
            name_item.setData(Qt.ItemDataRole.UserRole, str(profile.get("id", "")))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(str(profile.get("category", ""))))
            values = profile.get("values", {})
            self.table.setItem(row, 2, QTableWidgetItem(str(len(values) if isinstance(values, dict) else 0)))
            self.table.setItem(row, 3, QTableWidgetItem(str(profile.get("updated_at", ""))))

        has_profiles = self.table.rowCount() > 0
        self.empty_state.setVisible(not has_profiles)
        self.table.setVisible(has_profiles)
        self.delete_button.setEnabled(has_profiles)
        if has_profiles:
            self.table.selectRow(0)

    def _delete_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return

        profile_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        name = item.text()
        answer = QMessageBox.question(
            self,
            'Excluir perfil',
            f"Excluir o perfil de preenchimento '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.store.delete_profile(profile_id)
            self._reload()
            show_toast(
                self,
                'Perfil excluído',
                f'O perfil {name} foi removido.',
                kind='info',
            )
