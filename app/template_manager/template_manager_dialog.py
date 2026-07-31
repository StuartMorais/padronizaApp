from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.backup_manager import create_scheduled_backup
from app.dialogs.diagnostics_dialog import DiagnosticsDialog
from app.dialogs.version_history_dialog import VersionHistoryDialog
from app.favorite_store import FavoriteStore
from app.template_diagnostics import diagnose_template, diagnostics_text
from app.template_manager.template_editor_dialog import TemplateEditorDialog
from app.widgets.context_help import HelpIconButton
from app.widgets.empty_state import EmptyState
from app.widgets.toast import show_toast
from app.runtime_settings import APPLICATION, ORGANIZATION
from app.system_open import SystemOpenError, open_file, open_folder
from app.template_repository import (
    DuplicateTemplateFileError,
    SimilarTemplateNameError,
    TemplateRepository,
)


class TemplateManagerDialog(QDialog):
    def __init__(
        self,
        templates_dir: Path,
        favorite_store: FavoriteStore | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = TemplateRepository(templates_dir)
        self.favorite_store = favorite_store or FavoriteStore()
        self.project_root = Path(templates_dir).parent
        self.settings = QSettings(ORGANIZATION, APPLICATION)

        self.setWindowTitle('Gerenciar modelos')
        self.resize(1380, 720)
        self.setMinimumSize(1120, 600)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText('Pesquisar modelos...')
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._apply_filter)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            [
                'Favorito',
                'Nome',
                'Categoria',
                'Versão',
                'ID do modelo',
                'Status do arquivo',
                'Status do nome',
                'DOCX de origem',
            ]
        )
        header_help = [
            'Clique na estrela para adicionar ou remover dos favoritos.',
            'Nome apresentado na biblioteca e na página Gerar.',
            'Categoria usada para organizar e pesquisar modelos.',
            'Versão informativa do modelo atual.',
            'Identificador interno e estável do modelo.',
            'Avisa quando o mesmo conteúdo DOCX é usado por mais de um modelo.',
            'Avisa quando existem nomes muito semelhantes na biblioteca.',
            'Caminho do arquivo Word usado como base do modelo.',
        ]
        for column, help_text in enumerate(header_help):
            header_item = self.table.horizontalHeaderItem(column)
            if header_item is not None:
                header_item.setToolTip(help_text)
        self.table.setAlternatingRowColors(True)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemDoubleClicked.connect(lambda _item: self._edit_selected())
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(32)

        header = self.table.horizontalHeader()
        header.setStretchLastSection(True)
        for column in range(self.table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        for column, width in enumerate([82, 270, 145, 85, 210, 145, 155, 350]):
            self.table.setColumnWidth(column, width)

        title_label = QLabel(
            'Biblioteca de modelos'
        )
        title_label.setObjectName(
            "pageTitle"
        )

        self.new_button = QPushButton(
            'Novo modelo'
        )
        self.new_button.setObjectName(
            "primaryButton"
        )
        self.edit_button = QPushButton(
            'Editar'
        )
        self.duplicate_button = QPushButton(
            'Duplicar'
        )
        self.more_button = QPushButton(
            'Mais ações'
        )
        self.refresh_button = QPushButton(
            'Atualizar'
        )

        self.new_button.clicked.connect(
            self._create_template
        )
        self.edit_button.clicked.connect(
            self._edit_selected
        )
        self.duplicate_button.clicked.connect(
            self._duplicate_selected
        )
        self.refresh_button.clicked.connect(
            self._reload
        )

        self.more_menu = QMenu(self)

        self.favorite_action = QAction(
            'Adicionar aos favoritos',
            self,
        )
        self.favorite_action.triggered.connect(
            self._toggle_favorite
        )
        self.more_menu.addAction(
            self.favorite_action
        )

        self.import_action = QAction(
            'Importar pacote de modelo',
            self,
        )
        self.import_action.triggered.connect(
            self._import_package
        )
        self.more_menu.addAction(
            self.import_action
        )

        self.export_action = QAction(
            'Exportar pacote de modelo',
            self,
        )
        self.export_action.triggered.connect(
            self._export_selected
        )
        self.more_menu.addAction(
            self.export_action
        )

        self.more_menu.addSeparator()

        self.diagnostics_action = QAction(
            'Executar diagnóstico',
            self,
        )
        self.diagnostics_action.triggered.connect(
            self._diagnose_selected
        )
        self.more_menu.addAction(
            self.diagnostics_action
        )

        self.repeated_files_action = QAction(
            'Revisar arquivos de modelo repetidos',
            self,
        )
        self.repeated_files_action.triggered.connect(
            self._review_repeated_files
        )
        self.more_menu.addAction(
            self.repeated_files_action
        )

        self.similar_names_action = QAction(
            'Revisar nomes de modelos semelhantes',
            self,
        )
        self.similar_names_action.triggered.connect(
            self._review_similar_names
        )
        self.more_menu.addAction(
            self.similar_names_action
        )

        self.versions_action = QAction(
            'Histórico de versões',
            self,
        )
        self.versions_action.triggered.connect(
            self._show_versions
        )
        self.more_menu.addAction(
            self.versions_action
        )

        self.more_menu.addSeparator()

        self.archive_action = QAction(
            'Arquivar modelo',
            self,
        )
        self.archive_action.triggered.connect(
            self._archive_selected
        )
        self.more_menu.addAction(
            self.archive_action
        )

        self.delete_action = QAction(
            'Excluir permanentemente',
            self,
        )
        self.delete_action.triggered.connect(
            self._delete_selected
        )
        self.more_menu.addAction(
            self.delete_action
        )

        self.more_button.setMenu(
            self.more_menu
        )

        search_row = QHBoxLayout()
        search_row.addWidget(
            title_label
        )
        search_row.addWidget(
            HelpIconButton(
                'Biblioteca e status dos modelos',
                (
                    '<p><b>Status do arquivo</b> identifica modelos que usam o mesmo '
                    'conteúdo DOCX. <b>Status do nome</b> destaca nomes muito semelhantes.</p>'
                    '<p>Esses avisos não bloqueiam o uso, mas ajudam a evitar cadastros '
                    'duplicados ou difíceis de distinguir.</p>'
                    '<p>Clique duas vezes em uma linha para editar o modelo.</p>'
                ),
            )
        )
        search_row.addStretch()
        search_row.addWidget(
            self.search_input
        )
        search_row.addWidget(
            self.refresh_button
        )

        actions = QHBoxLayout()
        actions.addWidget(
            self.new_button
        )
        actions.addWidget(
            self.edit_button
        )
        actions.addWidget(
            self.duplicate_button
        )
        actions.addWidget(
            self.more_button
        )
        actions.addWidget(
            HelpIconButton(
                'Ações do Gerenciador de Modelos',
                (
                    '<p><b>Duplicar</b> cria uma nova entrada baseada no modelo atual. '
                    '<b>Importar/Exportar</b> transfere um pacote de modelo.</p>'
                    '<p><b>Diagnóstico</b> procura marcadores, campos e regras inválidas. '
                    '<b>Histórico de versões</b> permite restaurar uma cópia anterior.</p>'
                    '<p><b>Arquivar</b> é reversível. <b>Excluir permanentemente</b> remove '
                    'o modelo e deve ser usado somente quando a recuperação não for necessária.</p>'
                ),
            )
        )
        actions.addStretch()

        self.empty_state = EmptyState(
            'Nenhum modelo cadastrado',
            (
                'Crie um modelo a partir de um DOCX ou importe um pacote '
                'do Padroniza para começar a biblioteca.'
            ),
            icon='▦',
        )
        self.empty_state.add_action(
            'Novo modelo',
            self._create_template,
            primary=True,
        )
        self.empty_state.add_action(
            'Importar pacote',
            self._import_package,
        )

        self.no_results_state = EmptyState(
            'Nenhum modelo corresponde à pesquisa',
            'Tente outro termo ou limpe o campo de pesquisa para ver toda a biblioteca.',
            icon='⌕',
        )
        self.no_results_state.add_action(
            'Limpar pesquisa',
            self.search_input.clear,
            primary=True,
        )

        close_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Close
        )
        close_buttons.rejected.connect(
            self.reject
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            14,
            14,
            14,
            14,
        )
        layout.setSpacing(10)
        layout.addLayout(
            search_row
        )
        layout.addWidget(
            self.empty_state,
            1,
        )
        layout.addWidget(
            self.no_results_state,
            1,
        )
        layout.addWidget(
            self.table,
            1,
        )
        layout.addLayout(
            actions
        )
        layout.addWidget(
            close_buttons
        )

        self._reload()
        # The search field is the natural starting point when this dialog opens.
        # This also prevents a decorative help icon from receiving initial focus.
        self.search_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _reload(self, select_template_id: str | None = None) -> None:
        if select_template_id is None:
            select_template_id = self._selected_template_id()
        templates = self.repository.list_templates()
        self.favorite_store.prune(str(item["id"]) for item in templates)
        duplicate_groups = self.repository.find_duplicate_docx_groups()
        duplicate_by_id: dict[str, list[dict]] = {}
        for duplicate_members in duplicate_groups:
            for member in duplicate_members:
                duplicate_by_id[str(member.get("id", ""))] = duplicate_members

        similar_name_groups = self.repository.find_similar_name_groups()
        similar_name_by_id: dict[str, list[dict]] = {}
        for similar_members in similar_name_groups:
            for member in similar_members:
                similar_name_by_id[str(member.get("id", ""))] = similar_members

        self.table.setRowCount(0)
        selected_row: int | None = None

        for summary in templates:
            row = self.table.rowCount()
            self.table.insertRow(row)
            template_id = str(summary["id"])
            duplicate_group = duplicate_by_id.get(template_id, [])
            file_status = (
                f"⚠ Repetido ({len(duplicate_group)})"
                if duplicate_group
                else 'Único'
            )
            similar_name_group = similar_name_by_id.get(
                template_id,
                [],
            )
            name_status = (
                f"⚠ Semelhante ({len(similar_name_group)})"
                if similar_name_group
                else 'Único'
            )
            values = [
                "★" if self.favorite_store.is_favorite(template_id) else "☆",
                str(summary["name"]),
                str(summary.get("category", "")),
                str(summary.get("version", "1.0")),
                template_id,
                file_status,
                name_status,
                str(summary["source_path"]),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 5 and duplicate_group:
                    repeated_names = "\n".join(
                        str(member.get("name", member.get("id", 'Desconhecido')))
                        for member in duplicate_group
                    )
                    item.setToolTip(
                        "O mesmo conteúdo DOCX é usado por:\n"
                        + repeated_names
                    )
                elif column == 6 and similar_name_group:
                    similar_names = "\n".join(
                        str(member.get("name", member.get("id", 'Desconhecido')))
                        for member in similar_name_group
                    )
                    item.setToolTip(
                        "Nomes de modelos semelhantes neste grupo:\n"
                        + similar_names
                    )
                else:
                    item.setToolTip(value)
                if column in {0, 1}:
                    item.setData(Qt.ItemDataRole.UserRole, template_id)
                if column == 0:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row, column, item)
            if template_id == select_template_id:
                selected_row = row

        if selected_row is not None:
            self.table.selectRow(selected_row)
        elif self.table.rowCount() > 0:
            self.table.selectRow(0)
        self._apply_filter(self.search_input.text())
        self._update_buttons()

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().casefold()
        visible_rows = 0
        for row in range(self.table.rowCount()):
            haystack = " ".join(
                self.table.item(row, column).text() if self.table.item(row, column) else ""
                for column in range(self.table.columnCount())
            ).casefold()
            hidden = bool(needle and needle not in haystack)
            self.table.setRowHidden(row, hidden)
            if not hidden:
                visible_rows += 1

        has_templates = self.table.rowCount() > 0
        has_results = visible_rows > 0
        self.empty_state.setVisible(not has_templates)
        self.no_results_state.setVisible(has_templates and not has_results)
        self.table.setVisible(has_templates and has_results)

    def _selected_template_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 1)
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return str(value) if value else None

    def _selected_name(self) -> str:
        item = self.table.item(self.table.currentRow(), 1) if self.table.currentRow() >= 0 else None
        return item.text() if item else ""

    def _selected_source(self) -> Path | None:
        item = self.table.item(self.table.currentRow(), 7) if self.table.currentRow() >= 0 else None
        return Path(item.text()) if item else None

    def _update_buttons(self) -> None:
        template_id = self._selected_template_id()
        selected = template_id is not None

        self.edit_button.setEnabled(
            selected
        )
        self.duplicate_button.setEnabled(
            selected
        )
        self.more_button.setEnabled(
            True
        )

        for action in (
            self.favorite_action,
            self.export_action,
            self.diagnostics_action,
            self.versions_action,
            self.archive_action,
            self.delete_action,
        ):
            action.setEnabled(
                selected
            )

        favorite = bool(
            template_id
            and self.favorite_store.is_favorite(
                template_id
            )
        )
        self.favorite_action.setText(
            'Remover dos favoritos'
            if favorite
            else 'Adicionar aos favoritos'
        )

    def _create_template(self) -> None:
        dialog = TemplateEditorDialog(self.repository, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload(dialog.saved_template_id)
            show_toast(
                self,
                'Modelo criado',
                'O novo modelo já está disponível na biblioteca.',
            )

    def _edit_selected(self) -> None:
        template_id = self._selected_template_id()
        if not template_id:
            return
        dialog = TemplateEditorDialog(self.repository, template_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self._reload(template_id)
            show_toast(
                self,
                'Modelo atualizado',
                'As alterações foram salvas com sucesso.',
            )

    def _duplicate_selected(self) -> None:
        template_id = self._selected_template_id()
        if not template_id:
            return
        name, accepted = QInputDialog.getText(
            self,
            'Duplicar modelo',
            'Nome da cópia:',
            text=f"{self._selected_name()} - Cópia",
        )
        if not accepted or not name.strip():
            return
        try:
            new_id = self.repository.duplicate_template(
                template_id,
                name.strip(),
            )
        except SimilarTemplateNameError as exc:
            lines = "\n".join(
                f"• {match.get('name', match.get('id', 'Desconhecido'))} "
                f"— {round(float(match.get('similarity', 0.0)) * 100)}% de semelhança"
                for match in exc.matches
            )
            answer = QMessageBox.question(
                self,
                'Nome de modelo semelhante',
                f'O nome "{name.strip()}" é semelhante a:\n\n'
                f"{lines}\n\nCriar a cópia mesmo assim?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                new_id = self.repository.duplicate_template(
                    template_id,
                    name.strip(),
                    allow_similar_name=True,
                )
            except Exception as retry_exc:
                QMessageBox.critical(
                    self,
                    'Não foi possível duplicar o modelo',
                    str(retry_exc),
                )
                return
        except Exception as exc:
            QMessageBox.critical(self, 'Não foi possível duplicar o modelo', str(exc))
            return
        self._reload(new_id)
        show_toast(
            self,
            'Modelo duplicado',
            f'A cópia {name.strip()} foi criada.',
        )

    def _toggle_favorite(self) -> None:
        template_id = self._selected_template_id()
        if template_id:
            name = self._selected_name()
            favorite = self.favorite_store.toggle(template_id)
            self._reload(template_id)
            show_toast(
                self,
                'Favoritos atualizados',
                (
                    f'{name} foi adicionado aos favoritos.'
                    if favorite
                    else f'{name} foi removido dos favoritos.'
                ),
            )

    def _import_package(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            'Importar pacote de modelo',
            "",
            "Pacote de modelo do Padroniza (*.zip *.padroniza-template.zip)",
        )
        if not filename:
            return

        allow_duplicate = False
        allow_similar_name = False

        while True:
            try:
                template_id = self.repository.import_template_package(
                    Path(filename),
                    allow_duplicate=allow_duplicate,
                    allow_similar_name=allow_similar_name,
                )
                break
            except DuplicateTemplateFileError as exc:
                names = "\n".join(
                    f"• {match.get('name', match.get('id', 'Modelo desconhecido'))}"
                    for match in exc.matches
                )
                answer = QMessageBox.question(
                    self,
                    'Arquivo de modelo repetido',
                    "O pacote contém o mesmo DOCX de um modelo existente. "
                    f"\n\n{names}\n\nImportar mesmo assim?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                allow_duplicate = True
            except SimilarTemplateNameError as exc:
                names = "\n".join(
                    f"• {match.get('name', match.get('id', 'Desconhecido'))} "
                    f"— {round(float(match.get('similarity', 0.0)) * 100)}% de semelhança"
                    for match in exc.matches
                )
                answer = QMessageBox.question(
                    self,
                    'Nome de modelo semelhante',
                    f'O nome importado "{exc.name}" é semelhante a:\n\n'
                    f"{names}\n\nImportar mesmo assim?",
                    QMessageBox.StandardButton.Yes
                    | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                allow_similar_name = True
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    'Não foi possível importar o modelo',
                    str(exc),
                )
                return

        self._reload(template_id)
        show_toast(
            self,
            'Modelo importado',
            'O pacote foi adicionado à biblioteca com sucesso.',
        )

    def _review_repeated_files(self) -> None:
        self._show_group_report(
            title="Arquivos de modelo repetidos",
            empty_message="Nenhum arquivo DOCX repetido foi encontrado entre os modelos.",
            summary_label="grupo(s) de DOCX repetido(s)",
            groups=self.repository.find_duplicate_docx_groups(),
        )

    def _review_similar_names(self) -> None:
        self._show_group_report(
            title="Nomes de modelos semelhantes",
            empty_message="Nenhum nome de modelo semelhante foi encontrado.",
            summary_label="grupo(s) de nomes semelhantes",
            groups=self.repository.find_similar_name_groups(),
        )

    def _show_group_report(
        self,
        *,
        title: str,
        empty_message: str,
        summary_label: str,
        groups: list[list[dict]],
    ) -> None:
        if not groups:
            show_toast(
                self,
                title,
                empty_message,
                kind='info',
            )
            return

        sections: list[str] = []
        for index, members in enumerate(groups, start=1):
            lines = [
                f"Grupo {index} — {len(members)} modelos"
            ]
            lines.extend(
                f"• {item.get('name', item.get('id', 'Desconhecido'))} "
                f"({item.get('id', '')})"
                for item in members
            )
            sections.append("\n".join(lines))

        QMessageBox.warning(
            self,
            title,
            f"Foram encontrados {len(groups)} {summary_label}.\n\n"
            + "\n\n".join(sections),
        )

    def _export_selected(self) -> None:
        template_id = self._selected_template_id()
        if not template_id:
            return
        suggested = f"{template_id}.padroniza-template.zip"
        filename, _ = QFileDialog.getSaveFileName(
            self,
            'Exportar pacote de modelo',
            suggested,
            "Pacote de modelo do Padroniza (*.zip *.padroniza-template.zip)",
        )
        if not filename:
            return
        try:
            path = self.repository.export_template_package(template_id, Path(filename))
        except Exception as exc:
            QMessageBox.critical(self, 'Não foi possível exportar o modelo', str(exc))
            return
        show_toast(
            self,
            'Modelo exportado',
            f'Salvo em:\n{path}',
            duration=6000,
        )

    def _diagnose_selected(self) -> None:
        template_id = self._selected_template_id()
        if not template_id:
            return
        try:
            report = diagnose_template(
                self.repository.read_config(template_id),
                self.repository.get_source_path(template_id),
            )
        except Exception as exc:
            QMessageBox.critical(self, 'Falha no diagnóstico', str(exc))
            return
        DiagnosticsDialog('Diagnóstico do modelo', diagnostics_text(report), self).exec()

    def _show_versions(self) -> None:
        template_id = self._selected_template_id()
        if not template_id:
            return
        dialog = VersionHistoryDialog(self.repository, template_id, self)
        dialog.exec()
        if dialog.restored:
            self._reload(template_id)
            show_toast(
                self,
                'Versão restaurada',
                'A versão selecionada substituiu o modelo atual.',
            )

    def _create_safety_backup(self, reason: str) -> None:
        if not bool(self.settings.value("backup/before_destructive_actions", True, type=bool)):
            return
        backup_dir = Path(
            str(
                self.settings.value(
                    "backup/folder",
                    str(self.project_root / "backups"),
                )
            )
        )
        retention = int(
            self.settings.value(
                "backup/retention",
                7,
            )
            or 7
        )
        create_scheduled_backup(
            self.project_root,
            backup_dir,
            retention=retention,
            reason=reason,
        )

    def _archive_selected(self) -> None:
        template_id = self._selected_template_id()
        if not template_id:
            return
        if bool(self.settings.value("ui/confirm_destructive", True, type=bool)):
            answer = QMessageBox.question(
                self,
                'Arquivar modelo',
                f"Arquivar '{self._selected_name()}'?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self._create_safety_backup("before-archive")
            self.repository.archive_template(template_id)
            self.favorite_store.remove(template_id)
        except Exception as exc:
            QMessageBox.critical(self, 'Não foi possível arquivar o modelo', str(exc))
            return
        archived_name = self._selected_name() or template_id
        self._reload()
        show_toast(
            self,
            'Modelo arquivado',
            f'{archived_name} foi movido para Modelos arquivados.',
            kind='info',
        )

    def _delete_selected(self) -> None:
        template_id = self._selected_template_id()
        if not template_id:
            return
        if bool(self.settings.value("ui/confirm_destructive", True, type=bool)):
            answer = QMessageBox.warning(
                self,
                'Excluir modelo permanentemente',
                f"Excluir permanentemente '{self._selected_name()}'? Um backup de segurança será criado primeiro.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        try:
            self._create_safety_backup("before-delete")
            self.repository.permanently_delete_template(template_id)
            self.favorite_store.remove(template_id)
        except Exception as exc:
            QMessageBox.critical(self, 'Não foi possível excluir o modelo', str(exc))
            return
        self._reload()
        show_toast(
            self,
            'Modelo excluído',
            'O modelo foi removido permanentemente da biblioteca.',
            kind='info',
        )

    def _open_source(self) -> None:
        path = self._selected_source()
        if path and path.exists():
            try:
                open_file(path)
            except SystemOpenError as exc:
                QMessageBox.warning(
                    self,
                    'Não foi possível abrir o arquivo',
                    str(exc),
                )

    def _open_folder(self) -> None:
        path = self._selected_source()
        if path and path.parent.exists():
            try:
                open_folder(path.parent)
            except SystemOpenError as exc:
                QMessageBox.warning(
                    self,
                    'Não foi possível abrir a pasta',
                    str(exc),
                )

    def _show_context_menu(self, position) -> None:
        if self.table.itemAt(position) is None:
            return
        menu = QMenu(self)
        template_id = self._selected_template_id()
        favorite = bool(template_id and self.favorite_store.is_favorite(template_id))

        actions = [
            ('Remover dos favoritos' if favorite else 'Adicionar aos favoritos', self._toggle_favorite),
            ('Editar', self._edit_selected),
            ('Duplicar', self._duplicate_selected),
            ("Diagnóstico", self._diagnose_selected),
            ('Histórico de versões', self._show_versions),
            ("Exportar pacote", self._export_selected),
            ("Abrir DOCX de origem", self._open_source),
            ("Abrir pasta do modelo", self._open_folder),
            ('Arquivados', self._archive_selected),
            ("Excluir permanentemente", self._delete_selected),
        ]
        for index, (label, callback) in enumerate(actions):
            if index in {1, 6, 8}:
                menu.addSeparator()
            action = QAction(label, self)
            action.triggered.connect(callback)
            menu.addAction(action)
        menu.exec(self.table.viewport().mapToGlobal(position))
