from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.services.templates import TemplatePackage


class TemplateJsonExportDialog(QDialog):
    """Select one or several Padroniza models for portable JSON export."""

    def __init__(
        self,
        templates: list[TemplatePackage],
        *,
        active_template_id: str | None,
        multiple: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.multiple = bool(multiple)
        self.setWindowTitle("Selecionar modelos para exportar")
        self.resize(620, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Escolha os modelos")
        title.setObjectName("sectionTitle")
        hint = QLabel(
            "Marque as caixas dos modelos que deseja exportar."
            if self.multiple
            else "Selecione um modelo para exportar."
        )
        hint.setObjectName("mutedText")
        layout.addWidget(title)
        layout.addWidget(hint)

        self.template_list = QListWidget()
        self.template_list.setObjectName("jsonExportTemplateList")
        self.template_list.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
            if self.multiple
            else QAbstractItemView.SelectionMode.SingleSelection
        )
        for package in templates:
            details = " · ".join(
                value for value in (package.category, f"v{package.version}") if value
            )
            item = QListWidgetItem(
                f"{package.name}\n{details}" if details else package.name
            )
            item.setData(Qt.ItemDataRole.UserRole, package.template_id)
            if self.multiple:
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEnabled
                )
                item.setCheckState(
                    Qt.CheckState.Checked
                    if package.template_id == active_template_id
                    else Qt.CheckState.Unchecked
                )
            self.template_list.addItem(item)
            if not self.multiple and package.template_id == active_template_id:
                self.template_list.setCurrentItem(item)
        if not self.multiple and self.template_list.currentItem() is None and self.template_list.count():
            self.template_list.setCurrentRow(0)
        layout.addWidget(self.template_list, 1)

        self.selection_count = QLabel("")
        self.selection_count.setObjectName("mutedText")
        if self.multiple:
            selection_row = QHBoxLayout()
            select_all = QPushButton("Selecionar todos")
            clear_all = QPushButton("Limpar seleção")
            select_all.clicked.connect(lambda: self._set_all_checked(True))
            clear_all.clicked.connect(lambda: self._set_all_checked(False))
            selection_row.addWidget(select_all)
            selection_row.addWidget(clear_all)
            selection_row.addStretch(1)
            selection_row.addWidget(self.selection_count)
            layout.addLayout(selection_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Ok
        )
        self.export_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.export_button.setText("Exportar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if self.multiple:
            self.template_list.itemChanged.connect(self._update_selection_state)
        else:
            self.template_list.currentItemChanged.connect(self._update_selection_state)
            self.template_list.itemDoubleClicked.connect(lambda _item: self.accept())
        self._update_selection_state()

    def selected_template_ids(self) -> list[str]:
        if self.multiple:
            return [
                str(self.template_list.item(row).data(Qt.ItemDataRole.UserRole))
                for row in range(self.template_list.count())
                if self.template_list.item(row).checkState() == Qt.CheckState.Checked
            ]
        current = self.template_list.currentItem()
        return [str(current.data(Qt.ItemDataRole.UserRole))] if current is not None else []

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.template_list.blockSignals(True)
        try:
            for row in range(self.template_list.count()):
                self.template_list.item(row).setCheckState(state)
        finally:
            self.template_list.blockSignals(False)
        self._update_selection_state()

    def _update_selection_state(self, *_args: object) -> None:
        count = len(self.selected_template_ids())
        self.selection_count.setText(
            f"{count} selecionado" if count == 1 else f"{count} selecionados"
        )
        self.export_button.setEnabled(count > 0)
