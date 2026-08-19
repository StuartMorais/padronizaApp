from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from app.core.application_logging import report_exception


def show_exception_dialog(
    parent: QWidget | None,
    title: str,
    user_message: str,
    exc: BaseException,
    *,
    stage: str,
    context: dict[str, Any] | None = None,
) -> None:
    """Show a friendly error with a copyable technical report and error ID."""

    report = report_exception(stage, exc, context=context)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(user_message)
    box.setInformativeText(
        f"Código do erro: {report.error_id}\n"
        "Use ‘Mostrar detalhes’ ou copie os detalhes para diagnóstico."
    )
    box.setDetailedText(report.details)
    box.setStandardButtons(QMessageBox.StandardButton.Close)
    copy_button = box.addButton("Copiar detalhes", QMessageBox.ButtonRole.ActionRole)
    box.exec()
    if box.clickedButton() is copy_button:
        QApplication.clipboard().setText(report.details)
