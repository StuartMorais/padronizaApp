from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class HomePage(QWidget):
    """Página inicial com visão geral e atalhos dos fluxos principais."""

    navigate_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.metric_labels: dict[str, QLabel] = {}

        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 22, 24, 26)
        content_layout.setSpacing(18)

        content_layout.addWidget(self._create_hero())
        content_layout.addLayout(self._create_metrics())
        content_layout.addWidget(self._create_quick_actions())
        content_layout.addWidget(self._create_recent_panel())
        content_layout.addStretch()

        scroll.setWidget(content)
        page_layout.addWidget(scroll)

    def _create_hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("homeHero")

        layout = QHBoxLayout(hero)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(6)

        eyebrow = QLabel("PADRONIZA")
        eyebrow.setObjectName("homeEyebrow")

        title = QLabel('Bem-vindo')
        title.setObjectName("homeTitle")

        subtitle = QLabel(
            "Crie documentos padronizados, gerencie modelos reutilizáveis "
            "e converta arquivos sem sair do aplicativo."
        )
        subtitle.setObjectName("homeSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setMaximumWidth(720)

        text_layout.addWidget(eyebrow)
        text_layout.addWidget(title)
        text_layout.addWidget(subtitle)

        layout.addLayout(text_layout, 1)

        actions = QVBoxLayout()
        actions.setSpacing(8)

        create_button = QPushButton('Criar documento')
        create_button.setObjectName("primaryButton")
        create_button.setMinimumWidth(170)
        create_button.clicked.connect(
            lambda: self.navigate_requested.emit("generate")
        )

        templates_button = QPushButton('Gerenciar modelos')
        templates_button.setMinimumWidth(170)
        templates_button.clicked.connect(
            lambda: self.navigate_requested.emit("templates")
        )

        search_button = QPushButton('Pesquisar tudo')
        search_button.setMinimumWidth(170)
        search_button.setToolTip('Pesquisar modelos, documentos, perfis, arquivos e comandos (Ctrl+K)')
        search_button.clicked.connect(
            lambda: self.navigate_requested.emit("search")
        )

        actions.addWidget(create_button)
        actions.addWidget(templates_button)
        actions.addWidget(search_button)
        actions.addStretch()

        layout.addLayout(actions)
        return hero

    def _create_metrics(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        metrics = [
            (
                "templates",
                'Modelos',
                "Layouts de documentos disponíveis",
            ),
            (
                "favorites",
                'Favoritos',
                "Modelos usados com frequência",
            ),
            (
                "recent",
                'Documentos recentes',
                "Histórico de documentos gerados",
            ),
            (
                "profiles",
                "Perfis",
                "Dados reutilizáveis para preenchimento",
            ),
        ]

        for column, (key, title, caption) in enumerate(metrics):
            card = QFrame()
            card.setObjectName("homeMetricCard")

            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(16, 14, 16, 14)
            card_layout.setSpacing(3)

            value_label = QLabel("0")
            value_label.setObjectName("homeMetricValue")

            title_label = QLabel(title)
            title_label.setObjectName("homeMetricTitle")

            caption_label = QLabel(caption)
            caption_label.setObjectName("homeMetricCaption")
            caption_label.setWordWrap(True)

            card_layout.addWidget(value_label)
            card_layout.addWidget(title_label)
            card_layout.addWidget(caption_label)

            self.metric_labels[key] = value_label
            grid.addWidget(card, 0, column)
            grid.setColumnStretch(column, 1)

        return grid

    def _create_quick_actions(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("homePanel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        heading_row = QHBoxLayout()

        heading = QLabel('Ações rápidas')
        heading.setObjectName("homeSectionTitle")

        hint = QLabel('Escolha por onde começar')
        hint.setObjectName("homeSectionHint")

        heading_row.addWidget(heading)
        heading_row.addWidget(hint)
        heading_row.addStretch()
        layout.addLayout(heading_row)

        actions_grid = QGridLayout()
        actions_grid.setHorizontalSpacing(12)
        actions_grid.setVerticalSpacing(12)

        actions = [
            (
                'Novo documento',
                "Selecione um modelo, preencha as informações e gere um DOCX ou PDF.",
                "Abrir Gerar",
                "generate",
            ),
            (
                'Biblioteca de modelos',
                "Consulte os modelos instalados, crie novos e gerencie versões.",
                "Abrir Modelos",
                "templates",
            ),
            (
                'Converter arquivos',
                "Converta um DOCX existente em PDF ou um PDF em DOCX.",
                "Abrir Conversor",
                "converter",
            ),
            (
                "Aprender a usar o aplicativo",
                "Consulte o início rápido, o guia de botões, os atalhos e as instruções de modelos.",
                "Abrir Tutorial",
                "tutorial",
            ),
        ]

        for index, (title, description, button_text, target) in enumerate(actions):
            card = self._create_action_card(
                title=title,
                description=description,
                button_text=button_text,
                target=target,
            )
            actions_grid.addWidget(card, index // 2, index % 2)
            actions_grid.setColumnStretch(index % 2, 1)

        layout.addLayout(actions_grid)
        return panel

    def _create_action_card(
        self,
        *,
        title: str,
        description: str,
        button_text: str,
        target: str,
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("homeActionCard")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(7)

        title_label = QLabel(title)
        title_label.setObjectName("homeActionTitle")

        description_label = QLabel(description)
        description_label.setObjectName("homeActionText")
        description_label.setWordWrap(True)
        description_label.setMinimumHeight(40)

        button = QPushButton(button_text)
        button.setObjectName("homeActionButton")
        button.clicked.connect(
            lambda: self.navigate_requested.emit(target)
        )

        button_row = QHBoxLayout()
        button_row.addWidget(button)
        button_row.addStretch()

        layout.addWidget(title_label)
        layout.addWidget(description_label)
        layout.addLayout(button_row)
        return card

    def _create_recent_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("homePanel")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)

        heading_row = QHBoxLayout()

        heading = QLabel('Atividade recente')
        heading.setObjectName("homeSectionTitle")

        self.recent_summary = QLabel('Nenhum documento foi gerado ainda')
        self.recent_summary.setObjectName("homeSectionHint")

        view_all_button = QPushButton('Ver todos')
        view_all_button.clicked.connect(
            lambda: self.navigate_requested.emit("recent")
        )

        heading_row.addWidget(heading)
        heading_row.addWidget(self.recent_summary)
        heading_row.addStretch()
        heading_row.addWidget(view_all_button)
        layout.addLayout(heading_row)

        self.recent_table = QTableWidget(0, 4)
        self.recent_table.setObjectName("homeRecentTable")
        self.recent_table.setHorizontalHeaderLabels(
            [
                "Documento",
                'Modelo',
                'Criado em',
                'Formato',
            ]
        )
        self.recent_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.recent_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.recent_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.recent_table.setAlternatingRowColors(True)
        self.recent_table.setShowGrid(False)
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        self.recent_table.horizontalHeader().setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )
        self.recent_table.horizontalHeader().setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self.recent_table.horizontalHeader().setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        self.recent_table.setMinimumHeight(210)
        self.recent_table.itemDoubleClicked.connect(
            lambda _item: self.navigate_requested.emit("recent")
        )

        self.empty_recent_label = QLabel(
            "Os documentos gerados aparecerão aqui. "
            "Comece criando um documento a partir de um modelo."
        )
        self.empty_recent_label.setObjectName("homeEmptyState")
        self.empty_recent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_recent_label.setWordWrap(True)
        self.empty_recent_label.setMinimumHeight(150)

        layout.addWidget(self.empty_recent_label)
        layout.addWidget(self.recent_table)
        return panel

    def update_overview(
        self,
        *,
        template_count: int,
        favorite_count: int,
        recent_count: int,
        profile_count: int,
        recent_documents: list[dict[str, Any]],
    ) -> None:
        values = {
            "templates": template_count,
            "favorites": favorite_count,
            "recent": recent_count,
            "profiles": profile_count,
        }

        for key, value in values.items():
            label = self.metric_labels.get(key)
            if label is not None:
                label.setText(str(max(0, int(value))))

        self.recent_summary.setText(
            f"{recent_count} documento"
            if recent_count == 1
            else f"{recent_count} documentos"
        )

        visible_records = recent_documents[:5]
        self.recent_table.setRowCount(0)

        for record in visible_records:
            row = self.recent_table.rowCount()
            self.recent_table.insertRow(row)

            docx_path = str(record.get("docx_path", "")).strip()
            pdf_path = str(record.get("pdf_path", "")).strip()
            primary_path = docx_path or pdf_path

            filename = str(
                record.get(
                    "filename",
                    Path(primary_path).name,
                )
            ).strip() or "Documento gerado"

            template_name = str(
                record.get(
                    "template_name",
                    record.get("template_id", ""),
                )
            ).strip() or "—"

            created = self._format_created_at(
                str(record.get("created_at", ""))
            )

            if docx_path and pdf_path:
                file_format = "DOCX + PDF"
            elif pdf_path:
                file_format = "PDF"
            else:
                file_format = "DOCX"

            row_values = [
                filename,
                template_name,
                created,
                file_format,
            ]

            for column, value in enumerate(row_values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.recent_table.setItem(row, column, item)

        has_recent = bool(visible_records)
        self.empty_recent_label.setVisible(not has_recent)
        self.recent_table.setVisible(has_recent)

        if has_recent:
            self.recent_table.selectRow(0)

    @staticmethod
    def _format_created_at(value: str) -> str:
        value = value.strip()

        if not value:
            return "—"

        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return value

        return parsed.strftime("%d/%m/%Y %H:%M")
