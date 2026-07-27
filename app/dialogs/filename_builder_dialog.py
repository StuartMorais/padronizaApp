from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app.widgets.context_help import HelpLabel


class FilenameBuilderDialog(QDialog):
    TOKENS = [
        ('Modelo', "{{template.name}}"),
        ('Ano', "{{year}}"),
        ('Sequência', "{{sequence}}"),
        ('Número do processo', "{{process.number}}"),
        ('Nome da empresa', "{{company.legal_name}}"),
        ("CNPJ", "{{company.cnpj}}"),
    ]

    def __init__(self, pattern: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Montador de nome de arquivo')
        self.resize(650, 300)

        self.pattern_input = QLineEdit(pattern)
        self.preview_label = QLabel()
        self.preview_label.setWordWrap(True)
        self.preview_label.setObjectName("mutedText")
        self.pattern_input.textChanged.connect(self._update_preview)

        token_grid = QGridLayout()
        for index, (label, token) in enumerate(self.TOKENS):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=token: self._insert_token(value))
            token_grid.addWidget(button, index // 3, index % 3)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(
            HelpLabel(
                'Padrão do nome do arquivo',
                'Texto e marcadores do nome',
                (
                    '<p>Combine texto fixo e marcadores entre chaves duplas.</p>'
                    '<p>Durante a geração, cada marcador é substituído pelo conteúdo correspondente. '
                    'Caracteres inválidos para nomes de arquivo são tratados automaticamente.</p>'
                ),
            )
        )
        layout.addWidget(self.pattern_input)
        layout.addWidget(
            HelpLabel(
                'Inserir marcador',
                'Marcadores disponíveis',
                (
                    '<p>Clique em um botão para inserir o marcador na posição atual do cursor.</p>'
                    '<p>Também é possível digitar qualquer ID de campo, como '
                    '<b>{{representative.name}}</b>.</p>'
                ),
            )
        )
        layout.addLayout(token_grid)
        layout.addWidget(QLabel('Exemplo:'))
        layout.addWidget(self.preview_label)
        layout.addWidget(buttons)

        self._update_preview()

    def pattern(self) -> str:
        return self.pattern_input.text().strip()

    def _insert_token(self, token: str) -> None:
        cursor = self.pattern_input.cursorPosition()
        text = self.pattern_input.text()
        self.pattern_input.setText(text[:cursor] + token + text[cursor:])
        self.pattern_input.setCursorPosition(cursor + len(token))

    def _update_preview(self) -> None:
        preview = self.pattern_input.text()
        replacements = {
            "{{template.name}}": 'Proposta Comercial',
            "{{year}}": "2026",
            "{{sequence}}": "0001",
            "{{process.number}}": "123-2026",
            "{{company.legal_name}}": 'Empresa Exemplo Ltda.',
            "{{company.cnpj}}": "12.345.678-0001-95",
        }
        for token, value in replacements.items():
            preview = preview.replace(token, value)
        self.preview_label.setText(preview or "generated_document.docx")
