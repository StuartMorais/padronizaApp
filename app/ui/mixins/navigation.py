from __future__ import annotations

from pathlib import Path
from typing import Any
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

from app.ui.dialogs.global_search_dialog import GlobalSearchDialog
from app.core.system_open import SystemOpenError, open_folder
from app.ui.widgets.toast import show_toast

class NavigationMixin:
    def _show_converter_page(self, direction: str = "docx_to_pdf") -> None:
        index = self.pages.indexOf(self.converter_page)
        if index < 0:
            return
        self.sidebar.select_page(index)
        self.pages.setCurrentIndex(index)
        self.converter_page.focus_direction(direction)

    def _conversion_completed(
        self,
        direction: str,
        source: str,
        output: str,
    ) -> None:
        label = (
            'DOCX convertido para PDF'
            if direction == "docx_to_pdf"
            else 'PDF convertido para DOCX'
        )
        output_path = Path(output)
        self.status_message.setText(
            f"Convertido: {output_path.name}"
        )
        show_toast(
            self,
            'Conversão concluída',
            f'{output_path.name} foi criado com sucesso.',
        )
        self.local_store.add_audit(
            "file_converted",
            label,
            {
                "direction": direction,
                "source": source,
                "output": output,
            },
        )
        self._refresh_audit_page()

    def _global_search_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = [
            {"kind": "Comando", "name": 'Criar documento', "details": "Abrir a página Gerar", "action": "generate"},
            {"kind": "Comando", "name": 'Gerenciar modelos', "details": "Abrir a biblioteca de modelos", "action": "templates"},
            {"kind": "Comando", "name": 'Converter arquivos', "details": "Abrir a conversão de DOCX e PDF", "action": "converter"},
            {"kind": "Comando", "name": 'Configurações do aplicativo', "details": "Abrir as configurações", "action": "settings"},
            {"kind": "Comando", "name": 'Tutorial', "details": "Abrir o tutorial do aplicativo", "action": "tutorial"},
            {"kind": "Comando", "name": "Criar backup", "details": "Criar um backup ZIP", "callback": "backup"},
        ]
        favorite_ids = set(self.favorite_store.favorite_ids())
        for package in self.templates:
            records.append({
                "kind": "Modelo favorito" if package.template_id in favorite_ids else 'Modelo',
                "name": package.name,
                "details": f"{package.category} · {package.version} · {len(package.fields)} campos",
                "template_id": package.template_id,
                "path": str(package.source_path),
            })
        for item in self.local_store.list_recent():
            path = str(item.get("docx_path", "") or item.get("pdf_path", ""))
            records.append({
                "kind": "Documento",
                "name": str(item.get("filename", Path(path).name)),
                "details": f"{item.get('template_name', '')} · {item.get('process_number', '')} · {item.get('created_at', '')}",
                "recent_id": str(item.get("id", "")),
                "path": path,
            })
        for profile in self.local_store.list_profiles():
            records.append({
                "kind": 'Perfil',
                "name": str(profile.get("name", "")),
                "details": str(profile.get("category", "")),
                "profile_id": str(profile.get("id", "")),
                "action": "generate",
            })
        for archive in self.repository.list_archived_templates():
            records.append({
                "kind": "Modelo arquivado",
                "name": str(archive.get("name", archive.get("id", ""))),
                "details": str(archive.get("category", "")),
                "action": "archive",
                "path": str(archive.get("folder", "")),
            })
        return records

    def _show_global_search(self) -> None:
        dialog = GlobalSearchDialog(self._global_search_records(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_record:
            return
        record = dialog.selected_record
        if record.get("callback") == "backup":
            self._create_backup()
            return
        template_id = str(record.get("template_id", ""))
        if template_id:
            self._select_template_by_id(template_id)
            self._navigate_to_target("generate")
            return
        recent_id = str(record.get("recent_id", ""))
        if recent_id:
            self._navigate_to_target("recent")
            for row in range(self.recent_table.rowCount()):
                item = self.recent_table.item(row, 0)
                if item and str(item.data(Qt.ItemDataRole.UserRole) or "") == recent_id:
                    self.recent_table.selectRow(row)
                    break
            return
        profile_id = str(record.get("profile_id", ""))
        if profile_id:
            self._navigate_to_target("generate")
            index = self.profile_combo.findData(profile_id)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
                self._apply_selected_profile()
            return
        action = str(record.get("action", ""))
        if action:
            self._navigate_to_target(action)

    def _show_tutorial_page(self) -> None:
        index = self.pages.indexOf(self.tutorial_page)
        if index < 0:
            return
        self.sidebar.select_page(index)
        self.pages.setCurrentIndex(index)

    def _navigate_from_home(
        self,
        target: str,
    ) -> None:
        if target == "search":
            self._show_global_search()
            return
        self._navigate_to_target(
            target
        )

    def _navigate_from_tutorial(
        self,
        target: str,
    ) -> None:
        self._navigate_to_target(
            target
        )

    def _navigate_to_target(
        self,
        target: str,
    ) -> None:
        page_map = {
            "home": self.home_page,
            "generate": self.generate_page,
            "templates": self.templates_page,
            "recent": self.recent_page,
            "favorites": self.favorites_page,
            "archive": self.archive_page,
            "settings": self.settings_page,
            "converter": self.converter_page,
            "tutorial": self.tutorial_page,
        }

        page = page_map.get(target)

        if page is None:
            return

        index = self.pages.indexOf(page)

        if index < 0:
            return

        self.sidebar.select_page(index)
        self.pages.setCurrentIndex(index)

    def _change_page(
        self,
        index: int,
    ) -> None:
        self.pages.setCurrentIndex(index)
        page = self.pages.widget(index)

        if page is self.home_page:
            self._refresh_home_page()
        elif page is self.recent_page:
            self._refresh_recent_page()
        elif page is self.favorites_page:
            self._refresh_favorites_page()
        elif page is self.archive_page:
            self._refresh_archive_page()
        elif page is self.settings_page:
            self._refresh_audit_page()

    def _refresh_home_page(self) -> None:
        if not hasattr(
            self,
            "home_page",
        ):
            return

        active_template_ids = {
            package.template_id
            for package in self.templates
        }

        favorite_count = sum(
            1
            for template_id
            in self.favorite_store.favorite_ids()
            if template_id in active_template_ids
        )

        recent_documents = (
            self.local_store.list_recent()
        )
        profiles = (
            self.local_store.list_profiles()
        )

        self.home_page.update_overview(
            template_count=len(self.templates),
            favorite_count=favorite_count,
            recent_count=len(recent_documents),
            profile_count=len(profiles),
            recent_documents=recent_documents,
        )

    def _open_data_folder(self) -> None:
        self.project_root.mkdir(parents=True, exist_ok=True)
        try:
            open_folder(self.project_root)
        except SystemOpenError as exc:
            QMessageBox.warning(
                self,
                'Não foi possível abrir a pasta de dados',
                str(exc),
            )

    def _open_output_folder(self) -> None:
        folder = self._output_root()
        folder.mkdir(parents=True, exist_ok=True)
        try:
            open_folder(folder)
        except SystemOpenError as exc:
            QMessageBox.warning(
                self,
                'Não foi possível abrir a pasta',
                str(exc),
            )

    def _show_placeholder_guide(self) -> None:
        self._show_tutorial_page()
        self.tutorial_page.show_markers_tab()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            'Sobre o Padroniza',
            "Padroniza\n\n"
            "Geração de DOCX com validação de campos, perfis, rascunhos, documentos recentes, "
            "pacotes em lote, importação e exportação de modelos, histórico de versões, diagnósticos, "
            "conversão integrada de DOCX/PDF, numeração, backups e histórico de auditoria. Nenhum "
            "aplicativo externo de escritório é necessário para a conversão.",
        )
