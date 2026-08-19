from __future__ import annotations

from datetime import date, datetime
from PySide6.QtWidgets import QInputDialog, QMessageBox

from app.ui.dialogs.profile_manager_dialog import ProfileManagerDialog
from app.services.templates import TemplatePackage
from app.ui.widgets.toast import show_toast

from app.ui.dialogs.error_dialog import show_exception_dialog
class ProfileDraftMixin:
    def _refresh_profiles(self) -> None:
        current = self.profile_combo.currentData() if hasattr(self, "profile_combo") else None
        self.profile_combo.clear()
        self.profile_combo.addItem('Selecione um perfil salvo...', None)
        selected = 0
        for index, profile in enumerate(self.local_store.list_profiles(), start=1):
            self.profile_combo.addItem(
                f"{profile.get('name', '')} — {profile.get('category', '')}",
                str(profile.get("id", "")),
            )
            if str(profile.get("id", "")) == str(current):
                selected = index
        self.profile_combo.setCurrentIndex(selected)

    def _apply_selected_profile(self) -> None:
        profile_id = self.profile_combo.currentData()
        if not profile_id:
            return
        profile = self.local_store.get_profile(str(profile_id))
        if profile and isinstance(profile.get("values"), dict):
            applied_count = self.document_form.apply_profile(profile["values"])
            self._active_profile_id = str(profile.get("id", ""))
            self._active_profile_name = str(profile.get("name", ""))
            profile_name = str(profile.get("name", ""))
            if applied_count:
                self.status_message.setText(
                    f"Perfil aplicado: {profile_name} — {applied_count} campo(s) preenchido(s)"
                )
            else:
                self.status_message.setText(
                    f"Perfil sem campos compatíveis com este modelo: {profile_name}"
                )
                show_toast(
                    self,
                    'Perfil sem correspondências',
                    'Nenhum campo deste modelo corresponde aos dados salvos no perfil.',
                )

    def _save_profile(self) -> None:
        if self._selected_template() is None:
            return
        name, accepted = QInputDialog.getText(self, 'Salvar perfil de preenchimento', 'Nome do perfil:')
        if not accepted or not name.strip():
            return
        category, accepted = QInputDialog.getText(
            self,
            'Categoria do perfil',
            'Categoria:',
            text="Empresa",
        )
        if not accepted:
            return
        try:
            self.local_store.save_profile(
                name=name.strip(),
                category=category.strip() or "Empresa",
                values=self.document_form.profile_payload(),
            )
        except Exception as exc:
            show_exception_dialog(self, 'Não foi possível salvar o perfil', str(exc), exc, stage='profile_save')
            return
        self._refresh_profiles()
        self.status_message.setText(f"Perfil salvo: {name.strip()}")
        show_toast(
            self,
            'Perfil salvo',
            f'O perfil {name.strip()} está disponível para novos preenchimentos.',
        )

    def _manage_profiles(self) -> None:
        ProfileManagerDialog(self.local_store, self).exec()
        self._refresh_profiles()

    def _form_values_changed(self) -> None:
        if self._restoring_draft:
            return
        self._form_dirty = True
        self._schedule_draft_save()
        self._refresh_generation_state()

    def _schedule_draft_save(self) -> None:
        if (
            not self._restoring_draft
            and not self._draft_choice_pending
        ):
            self.draft_save_label.setText(
                "Salvando rascunho…"
            )
            self.autosave_timer.start()

    def _persist_current_draft(
        self,
        template_id: str,
    ) -> None:
        values = self.document_form.current_values()
        if self.document_form.has_meaningful_values(values):
            self.local_store.save_draft(
                template_id,
                values,
            )
        else:
            self.local_store.delete_draft(
                template_id
            )

    def _save_current_draft(self) -> None:
        package = self._selected_template()
        if (
            package is None
            or package.template_id
            != self._active_template_id
            or self._draft_choice_pending
            or not self._form_dirty
        ):
            return

        self._persist_current_draft(
            package.template_id
        )
        if self.document_form.has_meaningful_values():
            saved_at = datetime.now().strftime(
                "%H:%M"
            )
            self.draft_save_label.setText(
                f"Rascunho salvo às {saved_at}"
            )
            self.status_message.setText(
                "Rascunho salvo automaticamente"
            )
        else:
            self.draft_save_label.setText(
                "Sem rascunho pendente"
            )
        self._form_dirty = False

    def _offer_saved_draft(
        self,
        package: TemplatePackage,
    ) -> None:
        draft = self.local_store.load_draft(
            package.template_id
        )
        values = (
            draft.get("values")
            if isinstance(draft, dict)
            else None
        )
        if (
            not isinstance(values, dict)
            or not self.document_form.has_meaningful_values(
                values
            )
        ):
            if isinstance(draft, dict):
                self.local_store.delete_draft(
                    package.template_id
                )
            self._set_draft_choice_pending(False)
            self.draft_save_label.setText(
                "Salvamento automático ativo"
            )
            return

        self._pending_draft = draft
        self._set_draft_choice_pending(True)
        updated_at = self._friendly_draft_time(
            str(draft.get("updated_at", ""))
        )
        self.draft_message_label.setText(
            "Um rascunho deste modelo foi salvo"
            f" {updated_at}. Escolha como deseja continuar."
        )
        self.draft_save_label.setText(
            "Rascunho aguardando confirmação"
        )

    def _set_draft_choice_pending(
        self,
        pending: bool,
    ) -> None:
        self._draft_choice_pending = bool(pending)
        self.draft_banner.setVisible(
            self._draft_choice_pending
        )
        self.document_form.setEnabled(
            not self._draft_choice_pending
        )
        self.profile_group.setEnabled(
            not self._draft_choice_pending
        )

    def _continue_saved_draft(self) -> None:
        package = self._selected_template()
        draft = self._pending_draft
        values = (
            draft.get("values")
            if isinstance(draft, dict)
            else None
        )
        if package is None or not isinstance(values, dict):
            self._set_draft_choice_pending(False)
            self._refresh_generation_state()
            return

        self._set_draft_choice_pending(False)
        self._restoring_draft = True
        try:
            self.document_form.set_values(
                values,
                emit_signal=False,
            )
        finally:
            self._restoring_draft = False
        self._pending_draft = None
        self._form_dirty = False
        self.draft_save_label.setText(
            "Rascunho retomado"
        )
        self._refresh_generation_state()
        self.status_message.setText(
            "Preenchimento anterior restaurado"
        )

    def _discard_saved_draft(self) -> None:
        package = self._selected_template()
        if package is not None:
            self.local_store.delete_draft(
                package.template_id
            )
        self._pending_draft = None
        self._set_draft_choice_pending(False)
        self._form_dirty = False
        self.draft_save_label.setText(
            "Novo preenchimento"
        )
        self._refresh_generation_state()
        self.status_message.setText(
            "Novo preenchimento iniciado"
        )

    @staticmethod
    def _friendly_draft_time(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return "anteriormente"
        if parsed.date() == date.today():
            return f"hoje às {parsed.strftime('%H:%M')}"
        return f"em {parsed.strftime('%d/%m/%Y às %H:%M')}"

    def _clear_form(self) -> None:
        package = self._selected_template()
        if package is None or self._draft_choice_pending:
            return

        if (
            self.document_form.has_meaningful_values()
            and bool(
                self.settings.value(
                    "ui/confirm_destructive",
                    True,
                    type=bool,
                )
            )
        ):
            answer = QMessageBox.question(
                self,
                'Limpar formulário',
                'Remover todos os dados preenchidos neste modelo?',
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._restoring_draft = True
        try:
            self.document_form.clear_values()
        finally:
            self._restoring_draft = False
        self.autosave_timer.stop()
        self.local_store.delete_draft(
            package.template_id
        )
        self._form_dirty = False
        self._active_profile_id = None
        self._active_profile_name = ""
        self.draft_save_label.setText(
            "Sem rascunho pendente"
        )
        self._refresh_generation_state()
        self.status_message.setText(
            'Formulário limpo'
        )
