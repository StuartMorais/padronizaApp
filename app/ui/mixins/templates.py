from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QTableWidgetItem

from app.domain.field_metadata import uses_assisted_detection
from app.services.templates import TemplatePackage, discover_templates_with_issues
from app.ui.template_manager.template_editor_dialog import TemplateEditorDialog
from app.ui.widgets.toast import show_toast

class TemplateActionsMixin:
    def _load_templates(self) -> None:
        current_package = self._selected_template()
        current_id = (
            current_package.template_id
            if current_package is not None
            else None
        )
        if (
            self._active_template_id
            and self._form_dirty
            and not self._draft_choice_pending
        ):
            self.autosave_timer.stop()
            self._persist_current_draft(
                self._active_template_id
            )
            self._form_dirty = False
        self.templates, discovery_issues = discover_templates_with_issues(self.templates_dir)
        issue_signature = tuple(
            (str(issue.get("template_id", "")), str(issue.get("message", "")))
            for issue in discovery_issues
        )
        if discovery_issues and issue_signature != getattr(self, "_template_discovery_issue_signature", ()):
            preview = "; ".join(
                f"{issue.get('template_id', 'modelo')}: {issue.get('message', 'erro desconhecido')}"
                for issue in discovery_issues[:3]
            )
            if len(discovery_issues) > 3:
                preview += f"; e mais {len(discovery_issues) - 3}"
            show_toast(
                self,
                "Alguns modelos não puderam ser carregados",
                preview,
                kind="warning",
                duration=7000,
            )
        self._template_discovery_issue_signature = issue_signature
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        selected_index = 0
        for index, package in enumerate(self.templates):
            self.template_combo.addItem(package.name, package.template_id)
            if package.template_id == current_id:
                selected_index = index
        if self.templates:
            self.template_combo.setCurrentIndex(selected_index)
        self.template_combo.blockSignals(False)

        enabled = bool(self.templates)
        for button in (
            self.generate_button,
            self.pdf_button,
            self.sample_button,
            self.clear_button,
        ):
            button.setEnabled(enabled)
        self.template_count_label.setText(f"Modelos: {len(self.templates)}")
        self.favorite_store.prune(package.template_id for package in self.templates)
        self._refresh_template_overview()
        self._refresh_favorites_page()
        self._refresh_archive_page()
        self._update_favorite_controls()

        if enabled:
            self.generate_empty_state.hide()
            self.template_header.show()
            self.profile_group.show()
            self.document_form.show()
            self._render_selected_template()
        else:
            self.generate_empty_state.show()
            self.template_header.hide()
            self.assisted_detection_banner.hide()
            self.profile_group.hide()
            self.document_form.hide()
            self.document_form.set_template([], [])
            self.template_header.set_template(
                name='Nenhum modelo instalado',
                version="—",
                description='Abra Modelos para importar ou criar um modelo.',
                category="",
            )
            self._pending_draft = None
            self._set_draft_choice_pending(False)
            self._form_dirty = False
            self._refresh_generation_state()
            self.status_message.setText('Nenhum modelo carregado')

    def _selected_template(self) -> TemplatePackage | None:
        index = self.template_combo.currentIndex()
        return self.templates[index] if 0 <= index < len(self.templates) else None

    def _render_selected_template(self) -> None:
        package = self._selected_template()
        if package is None:
            return

        self.autosave_timer.stop()
        if (
            self._active_template_id
            and self._active_template_id != package.template_id
            and self._form_dirty
            and not self._draft_choice_pending
        ):
            self._persist_current_draft(
                self._active_template_id
            )

        self._active_template_id = package.template_id
        self._active_profile_id = None
        self._active_profile_name = ""
        self._form_dirty = False
        self._draft_choice_pending = False
        self._pending_draft = None
        self.template_header.set_template(
            name=package.name,
            version=package.version,
            description=package.description,
            category=package.category,
        )
        self.document_form.set_template(
            package.fields,
            package.config.get("sections", []),
        )
        self.assisted_detection_banner.setVisible(
            uses_assisted_detection(package.fields)
        )
        self._offer_saved_draft(package)
        self._update_favorite_controls()
        self._refresh_generation_state()
        self.status_message.setText(
            f"Carregado: {package.name}"
        )

    def _refresh_template_overview(self) -> None:
        panel = getattr(self, "template_manager_panel", None)
        if panel is None:
            return
        selected_id = (
            self._selected_template().template_id
            if self._selected_template() is not None
            else None
        )
        panel._reload(selected_id)

    def _use_template_from_library(self, template_id: str) -> None:
        if self._select_template_by_id(str(template_id)):
            self._navigate_to_target("generate")

    def _open_template_manager(self) -> None:
        # Model management now lives directly on the Modelos page.  Keep this
        # compatibility action for menus, empty states and global commands.
        self._navigate_to_target("templates")
        panel = getattr(self, "template_manager_panel", None)
        if panel is not None:
            panel._reload()
            panel.search_input.setFocus(Qt.FocusReason.OtherFocusReason)

    def _edit_active_template_field(self, field_id: str) -> None:
        self._edit_active_template(field_id)

    def _edit_active_template(self, field_id: str | bool | None = None) -> None:
        package = self._selected_template()
        if package is None:
            return

        # QPushButton.clicked may pass a bool. Only a string represents a field
        # requested by DocumentForm's inline "Corrigir" action.
        target_field = field_id if isinstance(field_id, str) else ""
        current_values = self.document_form.current_values()
        was_dirty = self._form_dirty

        dialog = TemplateEditorDialog(self.repository, package.template_id, self)
        if target_field:
            dialog.focus_field(target_field)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        # Reload the saved model but keep the user's current work wherever field
        # IDs still match. This makes fixing a detected field during filling a
        # natural workflow instead of forcing the user to start over.
        self._form_dirty = False
        self._load_templates()
        refreshed = self._selected_template()
        if refreshed is not None and refreshed.template_id == package.template_id:
            self.document_form.set_values(current_values, emit_signal=False)
            self._form_dirty = was_dirty or self.document_form.has_meaningful_values(
                current_values
            )
            if self._form_dirty:
                self.autosave_timer.start()
            self._refresh_generation_state()

        show_toast(
            self,
            "Modelo atualizado",
            "As alterações foram carregadas e os valores compatíveis foram mantidos.",
        )

    def _favorite_button_clicked(self, checked: bool) -> None:
        package = self._selected_template()
        if package:
            self.favorite_store.set_favorite(package.template_id, checked)
            self._refresh_favorites_page()
            self._update_favorite_controls()
            show_toast(
                self,
                'Favoritos atualizados',
                (
                    f'{package.name} foi adicionado aos favoritos.'
                    if checked
                    else f'{package.name} foi removido dos favoritos.'
                ),
            )

    def _toggle_selected_favorite(self) -> None:
        package = self._selected_template()
        if package:
            favorite = self.favorite_store.toggle(package.template_id)
            self._refresh_favorites_page()
            self._update_favorite_controls()
            show_toast(
                self,
                'Favoritos atualizados',
                (
                    f'{package.name} foi adicionado aos favoritos.'
                    if favorite
                    else f'{package.name} foi removido dos favoritos.'
                ),
            )

    def _update_favorite_controls(self) -> None:
        package = self._selected_template()
        favorite = bool(
            package
            and self.favorite_store.is_favorite(
                package.template_id
            )
        )

        self.favorite_button.blockSignals(True)
        self.favorite_button.setEnabled(
            package is not None
        )
        self.favorite_button.setChecked(
            favorite
        )
        self.favorite_button.setText(
            "★" if favorite else "☆"
        )
        self.favorite_button.setToolTip(
            "Remover modelo selecionado dos favoritos"
            if favorite
            else "Adicionar modelo selecionado aos favoritos"
        )
        self.favorite_button.blockSignals(False)

        self.favorite_menu_action.setEnabled(
            package is not None
        )
        self.favorite_menu_action.setText(
            'Remover modelo selecionado dos favoritos'
            if favorite
            else 'Adicionar modelo selecionado aos favoritos'
        )

    def _refresh_favorites_page(self) -> None:
        if not hasattr(self, "favorites_table"):
            return
        by_id = {package.template_id: package for package in self.templates}
        favorites = [by_id[value] for value in self.favorite_store.favorite_ids() if value in by_id]
        self.favorites_table.setRowCount(0)
        for package in favorites:
            row = self.favorites_table.rowCount()
            self.favorites_table.insertRow(row)
            values = [package.name, package.category, package.version, str(len(package.fields)), str(package.source_path)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, package.template_id)
                self.favorites_table.setItem(row, column, item)
        count = len(favorites)
        self.favorite_count_label.setText(
            f"{count} favorito" if count == 1 else f"{count} favoritos"
        )
        self.favorites_empty_state.setVisible(count == 0)
        self.favorites_table.setVisible(count > 0)
        self.use_favorite_button.setEnabled(count > 0)
        self.remove_favorite_button.setEnabled(count > 0)
        if count:
            self.favorites_table.selectRow(0)

    def _selected_favorite_id(self) -> str | None:
        row = self.favorites_table.currentRow()
        item = self.favorites_table.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return str(value) if value else None

    def _open_selected_favorite(self) -> None:
        template_id = self._selected_favorite_id()
        if template_id and self._select_template_by_id(template_id):
            self.sidebar.select_page(0)
            self.pages.setCurrentIndex(0)

    def _remove_selected_favorite(self) -> None:
        template_id = self._selected_favorite_id()
        if template_id:
            package = next(
                (item for item in self.templates if item.template_id == template_id),
                None,
            )
            self.favorite_store.remove(template_id)
            self._refresh_favorites_page()
            self._update_favorite_controls()
            show_toast(
                self,
                'Removido dos favoritos',
                (
                    f'{package.name} não aparece mais na lista de favoritos.'
                    if package is not None
                    else 'O modelo foi removido da lista de favoritos.'
                ),
            )

    def _show_favorites_page(self) -> None:
        self.sidebar.select_page(3)
        self.pages.setCurrentIndex(3)
        self._refresh_favorites_page()

    def _select_template_by_id(self, template_id: str) -> bool:
        for index, package in enumerate(self.templates):
            if package.template_id == template_id:
                self.template_combo.setCurrentIndex(index)
                return True
        return False
