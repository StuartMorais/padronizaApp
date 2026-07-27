from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QVBoxLayout,
)

from app.widgets.context_help import HelpLabel


class DiagnosticsDialog(QDialog):
    def __init__(self, title: str, report_text: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 620)

        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(report_text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(
            HelpLabel(
                'Relatório de diagnóstico',
                'Como interpretar o diagnóstico',
                (
                    '<p>O diagnóstico procura problemas no DOCX, nos marcadores, nos '
                    'campos e nas regras do modelo.</p>'
                    '<p>Erros devem ser corrigidos antes da geração. Avisos indicam itens '
                    'que merecem revisão, mas podem não impedir o uso.</p>'
                ),
            )
        )
        layout.addWidget(editor, 1)
        layout.addWidget(buttons)
