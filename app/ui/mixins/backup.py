from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from PySide6.QtWidgets import QFileDialog, QMessageBox, QTableWidgetItem

from app.ui.dialogs.backup_contents_dialog import BackupContentsDialog
from app.ui.dialogs.error_dialog import show_exception_dialog
from app.repositories.local_data import LocalDataStore
from app.repositories.templates import TemplateRepository
from app.services.backup import create_backup, create_scheduled_backup, inspect_backup, restore_backup
from app.ui.widgets.toast import show_toast

class BackupActionsMixin:
    def _refresh_audit_page(self) -> None:
        if not hasattr(self, "audit_table"):
            return
        self.audit_table.setRowCount(0)
        for entry in self.local_store.list_audit(limit=500):
            row = self.audit_table.rowCount()
            self.audit_table.insertRow(row)
            values = [entry.get("timestamp", ""), entry.get("action", ""), entry.get("description", "")]
            for column, value in enumerate(values):
                self.audit_table.setItem(row, column, QTableWidgetItem(str(value)))
        has_entries = self.audit_table.rowCount() > 0
        self.audit_empty_state.setVisible(not has_entries)
        self.audit_table.setVisible(has_entries)

    def _backup_configuration(
        self,
    ) -> tuple[Path, int]:
        folder = Path(
            str(
                self.settings.value(
                    "backup/folder",
                    str(
                        self.project_root
                        / "backups"
                    ),
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
        return folder, retention

    def _create_backup(self) -> None:
        folder, _retention = (
            self._backup_configuration()
        )
        suggested = (
            folder
            / (
                "padroniza-backup-"
                f"{date.today().isoformat()}"
                ".zip"
            )
        )
        filename, _ = (
            QFileDialog.getSaveFileName(
                self,
                "Criar backup do Padroniza",
                str(suggested),
                "Arquivo ZIP (*.zip)",
            )
        )
        if not filename:
            return

        try:
            path = create_backup(
                self.project_root,
                Path(filename),
                reason="manual",
            )
        except Exception as exc:
            show_exception_dialog(
                self, "Falha no backup", str(exc), exc,
                stage="backup_create", context={"destination": filename},
            )
            return

        self.local_store.add_audit(
            "backup_created",
            path.name,
            {
                "path": str(path),
            },
        )
        show_toast(
            self,
            'Backup criado',
            f'Salvo em:\n{path}',
            duration=6000,
        )

    def _choose_backup_archive(
        self,
        title: str,
    ) -> str:
        filename, _ = (
            QFileDialog.getOpenFileName(
                self,
                title,
                str(
                    self.backup_folder_input
                    .text()
                    .strip()
                ),
                "Arquivo ZIP (*.zip)",
            )
        )
        return filename

    def _read_backup_information(
        self,
        filename: str,
    ) -> dict[str, Any] | None:
        try:
            return inspect_backup(
                Path(filename)
            )
        except Exception as exc:
            show_exception_dialog(
                self, "Não foi possível ler o backup", str(exc), exc,
                stage="backup_inspect", context={"backup_path": filename},
            )
            return None

    def _select_backup_information(
        self,
        title: str,
    ) -> tuple[
        str,
        dict[str, Any],
    ] | None:
        filename = (
            self._choose_backup_archive(
                title
            )
        )
        if not filename:
            return None

        information = (
            self._read_backup_information(
                filename
            )
        )
        if information is None:
            return None

        return filename, information

    def _inspect_backup(self) -> None:
        selection = (
            self._select_backup_information(
                "Ver conteúdo do backup"
            )
        )
        if selection is None:
            return

        _filename, information = selection
        BackupContentsDialog(
            information,
            self,
        ).exec()

    def _run_scheduled_backup_if_due(
        self,
    ) -> None:
        if not bool(
            self.settings.value(
                "backup/automatic",
                False,
                type=bool,
            )
        ):
            return

        last = str(
            self.settings.value(
                "backup/last_automatic_date",
                "",
            )
        )
        today = date.today().isoformat()
        if last == today:
            return

        folder, retention = (
            self._backup_configuration()
        )
        try:
            path = create_scheduled_backup(
                self.project_root,
                folder,
                retention=retention,
                reason="automatic",
            )
        except Exception as exc:
            from app.core.application_logging import report_exception
            report_exception(
                "backup_automatic", exc, context={"backup_folder": folder}
            )
            self.status_message.setText(
                "Falha no backup automático: "
                f"{exc}"
            )
            return

        self.settings.setValue(
            "backup/last_automatic_date",
            today,
        )
        self.settings.sync()
        self.local_store.add_audit(
            "automatic_backup",
            path.name,
            {
                "path": str(path),
            },
        )
        self.status_message.setText(
            "Backup automático criado: "
            f"{path.name}"
        )

    def _create_pre_restore_backup(
        self,
    ) -> None:
        if not bool(
            self.settings.value(
                "backup/before_destructive_actions",
                True,
                type=bool,
            )
        ):
            return

        folder, retention = (
            self._backup_configuration()
        )
        create_scheduled_backup(
            self.project_root,
            folder,
            retention=retention,
            reason="before-restore",
        )

    def _restore_backup(self) -> None:
        selection = (
            self._select_backup_information(
                "Restaurar backup do Padroniza"
            )
        )
        if selection is None:
            return

        filename, information = selection

        BackupContentsDialog(
            information,
            self,
        ).exec()

        answer = QMessageBox.warning(
            self,
            "Restaurar backup",
            "A restauração substituirá os "
            "modelos, dados do aplicativo "
            "e configurações atuais. "
            "Deseja continuar?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if (
            answer
            != QMessageBox.StandardButton.Yes
        ):
            return

        try:
            self._create_pre_restore_backup()
            restore_backup(
                self.project_root,
                Path(filename),
            )
        except Exception as exc:
            show_exception_dialog(
                self, "Falha na restauração", str(exc), exc,
                stage="backup_restore", context={"backup_path": filename},
            )
            return

        self.local_store = LocalDataStore(
            self.data_dir
        )
        self.repository = (
            TemplateRepository(
                self.templates_dir
            )
        )
        self._load_preferences()
        self._load_templates()
        self._refresh_profiles()
        self._refresh_recent_page()
        self._refresh_archive_page()
        self._refresh_audit_page()
        show_toast(
            self,
            'Backup restaurado',
            'Os modelos, dados e configurações foram atualizados.',
            duration=6000,
        )
