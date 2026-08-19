from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.services.templates import TemplatePackage
from app.ui.widgets.context_help import HelpIconButton, HelpLabel


class BatchGenerationDialog(QDialog):
    def __init__(
        self,
        templates: list[TemplatePackage],
        current_template_id: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.templates = templates
        self.setWindowTitle('Gerar pacote de documentos')
        self.resize(820, 560)

        title = QLabel('Selecione os modelos que serão gerados com os dados atuais do formulário.')
        title.setWordWrap(True)

        self.package_name_input = QLineEdit('Documentos do processo')
        self.package_name_input.setPlaceholderText('Nome da pasta do pacote')

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Gerar', 'Modelo', 'Categoria', 'Campos'])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        for package in templates:
            row = self.table.rowCount()
            self.table.insertRow(row)
            check = QCheckBox()
            check.setChecked(package.template_id == current_template_id)
            check.setProperty("template_id", package.template_id)
            self.table.setCellWidget(row, 0, check)
            self.table.setItem(row, 1, QTableWidgetItem(package.name))
            self.table.setItem(row, 2, QTableWidgetItem(package.category))
            self.table.setItem(row, 3, QTableWidgetItem(str(len(package.fields))))

        self.create_zip_checkbox = QCheckBox('Criar um ZIP contendo o pacote gerado')
        self.create_zip_checkbox.setChecked(True)
        self.create_pdf_checkbox = QCheckBox('Criar também cópias em PDF')

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Gerar pacote')
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        options_row = QHBoxLayout()
        options_row.addWidget(self.create_zip_checkbox)
        options_row.addWidget(self.create_pdf_checkbox)
        options_row.addWidget(
            HelpIconButton(
                'Opções do pacote',
                (
                    '<p>Todos os modelos selecionados usam os dados atuais do formulário. '
                    'Campos que não existem em um modelo são simplesmente ignorados.</p>'
                    '<p>O ZIP reúne os resultados em um único arquivo. A opção PDF cria '
                    'uma cópia PDF de cada documento quando a conversão estiver disponível.</p>'
                ),
            )
        )
        options_row.addStretch()

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(
            HelpLabel(
                'Nome do pacote',
                'Nome da pasta e do ZIP',
                (
                    '<p>Este nome identifica a pasta criada para os documentos e, quando '
                    'ativado, o arquivo ZIP do pacote.</p>'
                ),
            )
        )
        layout.addWidget(self.package_name_input)
        layout.addWidget(self.table, 1)
        layout.addLayout(options_row)
        layout.addWidget(buttons)

    def selected_template_ids(self) -> list[str]:
        result: list[str] = []
        for row in range(self.table.rowCount()):
            check = self.table.cellWidget(row, 0)
            if isinstance(check, QCheckBox) and check.isChecked():
                template_id = str(check.property("template_id") or "")
                if template_id:
                    result.append(template_id)
        return result

    def package_name(self) -> str:
        return self.package_name_input.text().strip() or 'Documentos do processo'

    def create_zip(self) -> bool:
        return self.create_zip_checkbox.isChecked()

    def create_pdf(self) -> bool:
        return self.create_pdf_checkbox.isChecked()

    def _validate_and_accept(self) -> None:
        if not self.selected_template_ids():
            QMessageBox.warning(self, 'Nenhum modelo selecionado', 'Selecione pelo menos um modelo.')
            return
        self.accept()
