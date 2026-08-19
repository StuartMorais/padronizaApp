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

from app.repositories.templates import TemplateRepository
from app.ui.widgets.context_help import HelpLabel
from app.ui.widgets.empty_state import EmptyState


from app.ui.dialogs.error_dialog import show_exception_dialog
class VersionHistoryDialog(QDialog):
    def __init__(
        self,
        repository: TemplateRepository,
        template_id: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.template_id = template_id
        self.restored = False

        self.setWindowTitle('Histórico de versões do modelo')
        self.resize(760, 480)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Versão', 'Salvo em', 'Cópia de versão', "DOCX"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        self.empty_state = EmptyState(
            'Nenhuma versão anterior disponível',
            (
                'As cópias anteriores aparecerão aqui depois que o modelo '
                'for alterado e salvo novamente.'
            ),
            icon='↶',
        )
        self.empty_state.setMinimumHeight(180)

        self.restore_button = QPushButton('Restaurar versão selecionada')
        self.restore_button.clicked.connect(self._restore)

        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(
            HelpLabel(
                'Cópias anteriores do modelo',
                'Histórico de versões',
                (
                    '<p>Cada entrada representa uma cópia salva anteriormente da '
                    'configuração e, quando indicado, do DOCX.</p>'
                    '<p>Ao restaurar, a versão atual é preservada como uma nova cópia '
                    'antes de ser substituída.</p>'
                ),
            )
        )
        layout.addWidget(self.empty_state, 1)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.restore_button)
        layout.addWidget(close_buttons)

        self._reload()

    def _reload(self) -> None:
        self.table.setRowCount(0)
        for version in self.repository.list_versions(self.template_id):
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(str(version.get("version", "")))
            item.setData(Qt.ItemDataRole.UserRole, str(version.get("snapshot", "")))
            self.table.setItem(row, 0, item)
            self.table.setItem(row, 1, QTableWidgetItem(str(version.get("saved_at", ""))))
            self.table.setItem(row, 2, QTableWidgetItem(str(version.get("snapshot", ""))))
            self.table.setItem(row, 3, QTableWidgetItem('Sim' if version.get("has_docx") else 'Não'))

        has_versions = self.table.rowCount() > 0
        self.empty_state.setVisible(not has_versions)
        self.table.setVisible(has_versions)
        self.restore_button.setEnabled(has_versions)
        if has_versions:
            self.table.selectRow(0)

    def _restore(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        snapshot = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if not snapshot:
            return

        answer = QMessageBox.question(
            self,
            'Restaurar versão',
            'Restaurar esta versão do modelo? A versão atual será salva antes como uma nova cópia de versão.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self.repository.restore_version(self.template_id, snapshot)
        except Exception as exc:
            show_exception_dialog(self, 'Não foi possível restaurar a versão', str(exc), exc, stage='template_version_restore')
            return

        self.restored = True
        self.accept()
