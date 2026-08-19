from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from app.document.conversion.service import PdfConversionError
from app.document.docx.generator import DocumentGenerationError
from app.services.templates import TemplatePackage
from app.ui.widgets.toast import show_toast
from app.ui.dialogs.error_dialog import show_exception_dialog

class GenerationActionsMixin:
    def _refresh_generation_state(self) -> None:
        package = self._selected_template()
        if package is None:
            self._validation_issues = []
            self.document_form.set_validation_issues([])
            self.generate_context_label.setText(
                "Nenhum modelo selecionado"
            )
            self.validation_summary_label.setText(
                "Selecione um modelo para começar"
            )
            self.validation_summary_label.setProperty(
                "validationState",
                "blocked",
            )
            self.review_issues_button.hide()
            for button in (
                self.clear_button,
                self.sample_button,
                self.generate_button,
                self.pdf_button,
            ):
                button.setEnabled(False)
            self._repolish_widget(
                self.validation_summary_label
            )
            return

        values = self.document_form.current_values()
        filename = self.output_planner.filename_preview(
            package,
            values,
        )
        self.generate_context_label.setText(
            f"{package.name}  •  {filename}"
        )
        self.generate_context_label.setToolTip(
            f"Modelo selecionado: {package.name}\n"
            f"Nome previsto: {filename}"
        )

        if self._draft_choice_pending:
            self._validation_issues = []
            self.document_form.set_validation_issues([])
            self.validation_summary_label.setText(
                "Escolha como continuar o rascunho"
            )
            self.validation_summary_label.setProperty(
                "validationState",
                "warning",
            )
            self.review_issues_button.hide()
            ready = False
        else:
            issues = self.document_form.validation_issues(
                values
            )
            self._validation_issues = issues
            self.document_form.set_validation_issues(
                issues
            )
            self._validation_issue_index = min(
                self._validation_issue_index,
                max(0, len(issues) - 1),
            )

            missing_count = sum(
                1
                for issue in issues
                if issue.get("kind") == "missing"
            )
            invalid_count = len(issues) - missing_count
            if not issues:
                self.validation_summary_label.setText(
                    "Pronto para gerar"
                )
                self.validation_summary_label.setProperty(
                    "validationState",
                    "ready",
                )
                self.review_issues_button.hide()
                ready = True
            else:
                parts: list[str] = []
                if missing_count:
                    parts.append(
                        f"{missing_count} obrigatório"
                        if missing_count == 1
                        else f"{missing_count} obrigatórios"
                    )
                if invalid_count:
                    parts.append(
                        f"{invalid_count} inválido"
                        if invalid_count == 1
                        else f"{invalid_count} inválidos"
                    )
                self.validation_summary_label.setText(
                    "Pendências: " + " • ".join(parts)
                )
                self.validation_summary_label.setProperty(
                    "validationState",
                    "blocked",
                )
                self.review_issues_button.setText(
                    "Revisar pendência"
                    if len(issues) == 1
                    else f"Revisar {len(issues)} pendências"
                )
                self.review_issues_button.show()
                ready = False

        self._repolish_widget(
            self.validation_summary_label
        )
        self.clear_button.setEnabled(
            not self._draft_choice_pending
        )
        self.sample_button.setEnabled(
            not self._draft_choice_pending
        )
        self.generate_button.setEnabled(ready)
        self.pdf_button.setEnabled(ready)

        disabled_tip = (
            "Resolva as pendências indicadas antes de gerar."
            if self._validation_issues
            else "Escolha como continuar o rascunho."
        )
        for button in (
            self.generate_button,
            self.pdf_button,
        ):
            button.setToolTip(
                "" if ready else disabled_tip
            )

    def _review_next_issue(self) -> None:
        self._refresh_generation_state()
        if not self._validation_issues:
            return

        index = self._validation_issue_index % len(
            self._validation_issues
        )
        issue = self._validation_issues[index]
        self._validation_issue_index = (
            index + 1
        ) % len(self._validation_issues)

        field_id = str(
            issue.get("field_id", "")
        )
        self.document_form.reveal_validation_for(field_id)
        target = self.document_form.focus_field(
            field_id
        )
        if target is not None:
            self.generate_scroll.ensureWidgetVisible(
                target,
                24,
                90,
            )
        self.status_message.setText(
            str(issue.get("message", ""))
        )

    @staticmethod
    def _repolish_widget(widget: QWidget) -> None:
        style = widget.style()
        if style is None:
            return
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _load_sample_data(self) -> None:
        if (
            self._selected_template()
            and not self._draft_choice_pending
        ):
            self.document_form.load_sample_data()
            self._refresh_generation_state()
            self.status_message.setText(
                'Dados de exemplo carregados'
            )
            show_toast(
                self,
                'Dados de exemplo carregados',
                'Revise os dados antes de gerar o documento.',
                kind='info',
            )

    def _validate_fields(self) -> None:
        self._refresh_generation_state()
        if self._validation_issues:
            self.document_form.reveal_all_validation()
            self._review_next_issue()
            QMessageBox.warning(
                self,
                'Validação',
                'Ainda existem campos obrigatórios ausentes ou preenchimentos inválidos. '
                'O primeiro campo foi destacado.',
            )
            return
        show_toast(
            self,
            'Formulário válido',
            'Todos os campos obrigatórios visíveis e seus formatos estão corretos.',
        )

    def _collect_form_values(self) -> dict[str, Any] | None:
        self._refresh_generation_state()
        if self._draft_choice_pending:
            self.status_message.setText(
                'Escolha como continuar o rascunho antes de gerar.'
            )
            return None
        if self._validation_issues:
            self._review_next_issue()
            return None
        try:
            return self.document_form.collect_values()
        except ValueError as exc:
            self.status_message.setText(str(exc))
            self._refresh_generation_state()
            return None

    def _generate_document(self) -> None:
        package = self._selected_template()
        if package is None:
            return

        values = self._collect_form_values()
        if values is None:
            return

        planned = self.output_planner.plan(
            package,
            values,
            output_root=self._output_root(),
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            'Salvar documento DOCX',
            str(planned.path),
            "Documento do Word (*.docx)",
        )
        if not filename:
            return

        output_path = Path(filename)
        if output_path.suffix.lower() != ".docx":
            output_path = output_path.with_suffix(".docx")
        output_path = self._resolve_output_conflict(output_path)
        if output_path is None:
            return

        try:
            self.generation_service.generate_docx(
                package,
                values,
                output_path,
                profile_id=self._active_profile_id or "",
                profile_name=self._active_profile_name,
            )
        except DocumentGenerationError as exc:
            show_exception_dialog(
                self,
                'Falha na geração',
                str(exc),
                exc,
                stage="generate_docx",
                context={"template_id": package.template_id, "output_path": output_path},
            )
            self.status_message.setText('Falha na geração')
            return

        self._finish_single_generation(
            package=package,
            saved_path=output_path,
            message_title="DOCX criado",
            message_text=f"DOCX:\n{output_path}",
        )

    def _generate_pdf_document(self) -> None:
        package = self._selected_template()
        if package is None:
            return

        values = self._collect_form_values()
        if values is None:
            return

        planned = self.output_planner.plan(
            package,
            values,
            output_root=self._output_root(),
        )
        planned_pdf = planned.path.with_suffix(".pdf")

        filename, _ = QFileDialog.getSaveFileName(
            self,
            'Salvar documento PDF',
            str(planned_pdf),
            'Documento PDF (*.pdf)',
        )
        if not filename:
            return

        output_path = Path(filename)
        if output_path.suffix.lower() != ".pdf":
            output_path = output_path.with_suffix(".pdf")
        output_path = self._resolve_output_conflict(output_path)
        if output_path is None:
            return

        try:
            result = self.generation_service.generate_pdf(
                package,
                values,
                output_path,
                profile_id=self._active_profile_id or "",
                profile_name=self._active_profile_name,
            )
        except DocumentGenerationError as exc:
            show_exception_dialog(
                self, 'Falha na geração', str(exc), exc,
                stage="generate_pdf_docx_stage",
                context={"template_id": package.template_id, "output_path": output_path},
            )
            self.status_message.setText('Falha na geração')
            return
        except PdfConversionError as exc:
            show_exception_dialog(
                self, 'Falha na geração do PDF', str(exc), exc,
                stage="generate_pdf_conversion",
                context={
                    "template_id": package.template_id,
                    "output_path": output_path,
                    "backend": self.generation_service.converter.available_backend(),
                },
            )
            self.status_message.setText('Falha na geração do PDF')
            return

        self._finish_single_generation(
            package=package,
            saved_path=output_path,
            message_title="PDF criado",
            message_text=f"PDF:\n{output_path}",
        )
        if result.warnings:
            show_toast(
                self,
                f"PDF criado com {result.conversion_backend or 'conversor disponível'}",
                result.warnings[-1],
                kind="warning",
                duration=7000,
            )

    def _resolve_output_conflict(self, path: Path) -> Path | None:
        path = Path(path)
        if not path.exists():
            return path

        mode = str(self.settings.value("output/conflict", "rename"))
        if mode == "replace":
            return path
        if mode == "timestamp":
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            return path.with_name(f"{path.stem}_{stamp}{path.suffix}")
        if mode == "ask":
            answer = QMessageBox.question(
                self,
                'O arquivo já existe',
                f"Substituir o arquivo existente?\n\n{path}",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                return path
            if answer == QMessageBox.StandardButton.Cancel:
                return None

        return self._unique_output_path(path)

    @staticmethod
    def _unique_output_path(path: Path) -> Path:
        path = Path(path)
        if not path.exists():
            return path

        counter = 2
        while True:
            candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _finish_single_generation(
        self,
        *,
        package: TemplatePackage,
        saved_path: Path,
        message_title: str,
        message_text: str,
    ) -> None:
        self.autosave_timer.stop()
        self.local_store.delete_draft(
            package.template_id
        )
        self._form_dirty = False
        self.draft_save_label.setText(
            "Documento gerado — sem rascunho pendente"
        )
        self._refresh_generation_state()
        self._refresh_recent_page()
        self._refresh_audit_page()
        self.status_message.setText(
            f"Salvo: {saved_path.name}"
        )
        show_toast(
            self,
            message_title,
            message_text,
            duration=6000,
        )
