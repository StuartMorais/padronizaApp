from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import QFileDialog

from app.core.paths import is_transient_pyinstaller_path
from app.document.conversion.service import DEFAULT_CONVERTER
from app.core.settings import PORTABLE_MARKER, set_portable_mode
from app.ui.theme import ThemeManager

class SettingsMixin:
    def _load_preferences(self) -> None:
        self._loading_preferences = True
        theme = self.theme_manager.current_theme()
        index = self.theme_combo.findData(theme)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(index, 0))
        self.theme_combo.blockSignals(False)
        self.output_root_input.setText(str(self._output_root()))

        self.font_size_spin.blockSignals(True)
        self.font_size_spin.setValue(int(self.settings.value("accessibility/font_size", 10) or 10))
        self.font_size_spin.blockSignals(False)
        self.high_contrast_checkbox.setChecked(
            bool(self.settings.value("accessibility/high_contrast", False, type=bool))
        )
        self.confirmations_checkbox.setChecked(
            bool(self.settings.value("ui/confirm_destructive", True, type=bool))
        )

        conflict = str(self.settings.value("output/conflict", "rename"))
        conflict_index = self.output_conflict_combo.findData(conflict)
        self.output_conflict_combo.setCurrentIndex(max(0, conflict_index))

        self.portable_checkbox.blockSignals(True)
        if self.managed_storage:
            self.portable_checkbox.setChecked(True)
        else:
            self.portable_checkbox.setChecked(
                (self.project_root / PORTABLE_MARKER).exists()
            )
        self.portable_checkbox.blockSignals(False)

        self.auto_backup_checkbox.setChecked(
            bool(self.settings.value("backup/automatic", False, type=bool))
        )
        self.before_destructive_checkbox.setChecked(
            bool(self.settings.value("backup/before_destructive_actions", True, type=bool))
        )
        configured_backup_folder = str(
            self.settings.value(
                "backup/folder",
                str(self.project_root / "backups"),
            )
            or ""
        ).strip()
        if (
            not configured_backup_folder
            or is_transient_pyinstaller_path(configured_backup_folder)
        ):
            configured_backup_folder = str(self.project_root / "backups")
            self.settings.remove("backup/folder")
        self.backup_folder_input.setText(configured_backup_folder)
        self.backup_retention_spin.setValue(
            int(
                self.settings.value(
                    "backup/retention",
                    7,
                )
                or 7
            )
        )

        converter = DEFAULT_CONVERTER.available_backend()
        available = [info.name for info in DEFAULT_CONVERTER.backend_info() if info.available]
        fallback_text = " → ".join(available) if available else "nenhum backend disponível"
        self.converter_label.setText(
            f"Conversão DOCX → PDF: {converter}. Ordem disponível: {fallback_text}. "
            "O Padroniza usa automaticamente o backend de maior fidelidade e recorre ao integrado quando necessário."
        )
        self._loading_preferences = False
        self.theme_manager.apply_theme(theme)

    def _save_preferences(self, *_args) -> None:
        if self._loading_preferences:
            return
        self.settings.setValue("output/root", self.output_root_input.text().strip())
        self.settings.setValue("output/conflict", self.output_conflict_combo.currentData() or "rename")
        self.settings.setValue("accessibility/font_size", self.font_size_spin.value())
        self.settings.setValue("accessibility/high_contrast", self.high_contrast_checkbox.isChecked())
        self.settings.setValue("ui/confirm_destructive", self.confirmations_checkbox.isChecked())
        self.settings.setValue("backup/automatic", self.auto_backup_checkbox.isChecked())
        self.settings.setValue("backup/before_destructive_actions", self.before_destructive_checkbox.isChecked())
        self.settings.setValue("backup/folder", self.backup_folder_input.text().strip())
        self.settings.setValue(
            "backup/retention",
            self.backup_retention_spin.value(),
        )
        self.settings.sync()
        if not self.managed_storage:
            set_portable_mode(
                self.project_root,
                self.portable_checkbox.isChecked(),
            )
        self.theme_manager.apply_theme(self.theme_manager.current_theme())

    def _browse_backup_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecionar pasta de backups",
            self.backup_folder_input.text().strip() or str(self.project_root),
        )
        if folder:
            self.backup_folder_input.setText(folder)
            self._save_preferences()

    def _output_root(self) -> Path:
        configured = str(
            self.settings.value(
                "output/root",
                "",
            )
            or ""
        ).strip()

        if configured and not is_transient_pyinstaller_path(configured):
            return Path(configured).expanduser()

        if configured:
            self.settings.remove("output/root")
            self.settings.sync()

        return self.default_output_dir

    def _browse_output_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Selecionar pasta raiz de saída", str(self._output_root()))
        if folder:
            self.output_root_input.setText(folder)
            self._save_preferences()

    def _theme_combo_changed(self) -> None:
        theme = self.theme_combo.currentData()
        if theme:
            self._apply_theme(str(theme))

    def _set_dark_mode(self, enabled: bool) -> None:
        self._apply_theme(ThemeManager.DARK if enabled else ThemeManager.LIGHT)

    def _apply_theme(self, theme: str) -> None:
        self.theme_manager.apply_theme(theme)
        dark = theme == ThemeManager.DARK
        self.dark_mode_action.blockSignals(True)
        self.dark_mode_action.setChecked(dark)
        self.dark_mode_action.blockSignals(False)
        index = self.theme_combo.findData(theme)
        if index >= 0:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(index)
            self.theme_combo.blockSignals(False)
