from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog, QMessageBox, QTableWidgetItem

from app.domain.conditions import condition_matches
from app.domain.validation import validate_field
from app.domain.profile_mapping import build_profile_payload, resolve_profile_values
from app.services.templates import TemplatePackage
from app.core.system_open import SystemOpenError, open_file, open_folder
from app.ui.widgets.toast import show_toast

from app.ui.dialogs.error_dialog import show_exception_dialog
class RecentArchiveMixin:
    @staticmethod
    def _values_for_template(package: TemplatePackage, source_values: dict[str, Any]) -> dict[str, Any]:
        # Reuse the same stable identity resolver used by "Aplicar perfil" so
        # history/batch cross-template reuse behaves consistently for tagged,
        # native and automatically detected fields.
        matched = resolve_profile_values(package.fields, source_values)
        result: dict[str, Any] = {}
        for field in package.fields:
            field_id = str(field.get("id", ""))
            field_type = str(field.get("type", "text"))
            if field_id in matched:
                result[field_id] = matched[field_id]
            elif field_type == "checkbox":
                result[field_id] = False
            elif field_type == "date":
                result[field_id] = date.today().strftime("%d/%m/%Y")
            else:
                result[field_id] = ""
        return result

    @staticmethod
    def _missing_required_for_package(package: TemplatePackage, values: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for field in package.fields:
            if not condition_matches(field.get("visible_when"), values):
                continue
            error = validate_field(field, values.get(str(field.get("id", ""))))
            if error:
                errors.append(error)
        return errors

    def _refresh_recent_page(self) -> None:
        if not hasattr(self, "recent_table"):
            return
        self.recent_table.setRowCount(0)
        for record in self.local_store.list_recent():
            row = self.recent_table.rowCount()
            self.recent_table.insertRow(row)
            docx_path = str(record.get("docx_path", ""))
            pdf_path = str(record.get("pdf_path", ""))
            primary_path = docx_path or pdf_path
            values = [
                str(record.get("created_at", "")),
                str(record.get("filename", Path(primary_path).name)),
                str(record.get("template_name", record.get("template_id", ""))),
                str(record.get("process_number", "")),
                str(record.get("profile_name", "")),
                'Sim' if pdf_path else 'Não',
                primary_path,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, str(record.get("id", "")))
                self.recent_table.setItem(row, column, item)
        has_recent = self.recent_table.rowCount() > 0
        self.recent_empty_state.setVisible(not has_recent)
        self.recent_table.setVisible(has_recent)
        self.recent_actions_widget.setVisible(has_recent)
        if has_recent:
            self.recent_table.selectRow(0)

    def _selected_recent(self) -> dict[str, Any] | None:
        row = self.recent_table.currentRow()
        item = self.recent_table.item(row, 0) if row >= 0 else None
        record_id = str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""
        return self.local_store.get_recent(record_id) if record_id else None

    def _recent_output_path(
        self,
        record: dict[str, Any] | None,
    ) -> Path | None:
        if not record:
            return None

        raw_path = str(
            record.get("docx_path", "")
            or record.get("pdf_path", "")
        ).strip()
        return Path(raw_path) if raw_path else None

    def _open_recent_document(self) -> None:
        record = self._selected_recent()
        path = self._recent_output_path(record)
        if path and path.exists():
            try:
                open_file(path)
            except SystemOpenError as exc:
                QMessageBox.warning(
                    self,
                    'Não foi possível abrir o arquivo',
                    str(exc),
                )
        elif record:
            QMessageBox.warning(
                self,
                'Arquivo não encontrado',
                "O arquivo gerado não está mais "
                "no caminho registrado.",
            )

    def _open_recent_folder(self) -> None:
        record = self._selected_recent()
        path = self._recent_output_path(record)
        if path and path.parent.exists():
            try:
                open_folder(path.parent)
            except SystemOpenError as exc:
                QMessageBox.warning(
                    self,
                    'Não foi possível abrir a pasta',
                    str(exc),
                )

    def _edit_recent_data(self) -> None:
        record = self._selected_recent()
        if not record:
            return
        if not self._select_template_by_id(str(record.get("template_id", ""))):
            QMessageBox.warning(self, 'Modelo indisponível', 'O modelo usado por este registro não está instalado.')
            return
        self.document_form.set_values(record.get("values", {}))
        self.sidebar.select_page(0)
        self.pages.setCurrentIndex(0)

    def _regenerate_recent(self) -> None:
        record = self._selected_recent()
        if not record:
            return

        generate_pdf = bool(
            record.get("pdf_path")
            and not record.get("docx_path")
        )
        self._edit_recent_data()

        if generate_pdf:
            self._generate_pdf_document()
        else:
            self._generate_document()

    def _use_recent_with_another_template(self) -> None:
        record = self._selected_recent()
        if not record or not self.templates:
            return
        names = [package.name for package in self.templates]
        selected, accepted = QInputDialog.getItem(
            self,
            'Usar outro modelo',
            "Modelo:",
            names,
            0,
            False,
        )
        if not accepted:
            return
        index = names.index(selected)
        source_values = dict(record.get("values", {}))
        source_package = next(
            (package for package in self.templates if package.template_id == str(record.get("template_id", ""))),
            None,
        )
        if source_package is not None:
            # Attach V2 identity metadata before reusing a historical record in
            # another template. This gives non-tagged native/automatic fields
            # the same portability as saved profiles.
            source_values = build_profile_payload(source_package.fields, source_values)

        self.template_combo.setCurrentIndex(index)
        target_package = self._selected_template()
        if target_package is not None:
            self.document_form.set_values(self._values_for_template(target_package, source_values))
        self.sidebar.select_page(0)
        self.pages.setCurrentIndex(0)

    def _remove_recent_entry(self) -> None:
        record = self._selected_recent()
        if record:
            self.local_store.delete_recent(str(record.get("id", "")))
            self._refresh_recent_page()
            show_toast(
                self,
                'Registro removido',
                'O documento foi removido do histórico. O arquivo continua no disco.',
                kind='info',
            )

    def _clear_recent_history(self) -> None:
        confirmed = True
        if bool(self.settings.value("ui/confirm_destructive", True, type=bool)):
            answer = QMessageBox.question(
                self,
                'Limpar histórico recente',
                'Remover todos os registros de documentos recentes? Os arquivos gerados não serão excluídos.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            confirmed = answer == QMessageBox.StandardButton.Yes
        if confirmed:
            self.local_store.clear_recent()
            self._refresh_recent_page()
            show_toast(
                self,
                'Histórico limpo',
                'Os registros foram removidos. Os arquivos gerados não foram excluídos.',
                kind='info',
            )

    def _refresh_archive_page(self) -> None:
        if not hasattr(self, "archive_table"):
            return
        self.archive_table.setRowCount(0)
        for item in self.repository.list_archived_templates():
            row = self.archive_table.rowCount()
            self.archive_table.insertRow(row)
            values = [item["name"], item["category"], item["version"], str(item["folder"])]
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                if column == 0:
                    table_item.setData(Qt.ItemDataRole.UserRole, str(item["archive_id"]))
                self.archive_table.setItem(row, column, table_item)
        has_archived = self.archive_table.rowCount() > 0
        self.archive_empty_state.setVisible(not has_archived)
        self.archive_table.setVisible(has_archived)
        self.archive_actions_widget.setVisible(has_archived)
        if has_archived:
            self.archive_table.selectRow(0)

    def _selected_archive_id(self) -> str | None:
        row = self.archive_table.currentRow()
        item = self.archive_table.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return str(value) if value else None

    def _restore_archived_template(self) -> None:
        archive_id = self._selected_archive_id()
        if not archive_id:
            return
        try:
            template_id = self.repository.restore_archived_template(archive_id)
        except Exception as exc:
            show_exception_dialog(self, 'Não foi possível restaurar o modelo', str(exc), exc, stage='template_restore')
            return
        self.local_store.add_audit("template_restored", template_id, {})
        self._load_templates()
        self._select_template_by_id(template_id)
        show_toast(
            self,
            'Modelo restaurado',
            'O modelo voltou para a biblioteca ativa.',
        )

    def _open_archive_folder(self) -> None:
        archive_id = self._selected_archive_id()
        if archive_id:
            folder = self.repository.archive_dir / archive_id
            if folder.exists():
                try:
                    open_folder(folder)
                except SystemOpenError as exc:
                    QMessageBox.warning(
                        self,
                        'Não foi possível abrir a pasta',
                        str(exc),
                    )
