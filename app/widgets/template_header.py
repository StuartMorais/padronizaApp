from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)


class TemplateHeader(QFrame):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setObjectName("templateCard")

        self.icon_label = QLabel("DOCX")
        self.icon_label.setObjectName(
            "documentIcon"
        )
        self.icon_label.setFixedSize(
            58,
            58,
        )
        self.icon_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.title_label = QLabel(
            'Selecione um modelo'
        )
        self.title_label.setObjectName(
            "templateTitle"
        )

        self.version_label = QLabel("")
        self.version_label.setObjectName(
            "versionBadge"
        )

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        title_row.addWidget(
            self.title_label
        )
        title_row.addWidget(
            self.version_label
        )
        title_row.addStretch()

        self.description_label = QLabel(
            'Selecione um modelo para começar.'
        )
        self.description_label.setWordWrap(True)
        self.description_label.setObjectName(
            "mutedText"
        )

        self.category_label = QLabel("")
        self.category_label.setObjectName(
            "informationBadge"
        )

        self.format_label = QLabel(
            'Formato: DOCX'
        )
        self.format_label.setObjectName(
            "informationBadge"
        )

        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)
        badge_row.addWidget(
            self.category_label
        )
        badge_row.addWidget(
            self.format_label
        )
        badge_row.addStretch()

        information_layout = QVBoxLayout()
        information_layout.setSpacing(6)
        information_layout.addLayout(
            title_row
        )
        information_layout.addWidget(
            self.description_label
        )
        information_layout.addLayout(
            badge_row
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            18,
            16,
            18,
            16,
        )
        layout.setSpacing(18)
        layout.addWidget(
            self.icon_label
        )
        layout.addLayout(
            information_layout,
            1,
        )

    def set_template(
        self,
        *,
        name: str,
        version: str,
        description: str,
        category: str,
    ) -> None:
        self.title_label.setText(
            name or "Modelo sem nome"
        )
        self.version_label.setText(
            f"v{version or '1.0'}"
        )
        self.description_label.setText(
            description
            or "Nenhuma descrição foi informada."
        )

        category_text = (
            f"Categoria: {category}"
            if category
            else "Categoria: não definida"
        )
        self.category_label.setText(
            category_text
        )
