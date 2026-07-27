from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem


class Sidebar(QListWidget):
    page_changed = Signal(int)

    SECTIONS = [
        (
            'ÁREA DE TRABALHO',
            [
                ('⌂  Início', 8),
                ('▣  Gerar', 0),
                ('◷  Documentos recentes', 2),
                ('⇄  Converter arquivos', 6),
            ],
        ),
        (
            'BIBLIOTECA DE MODELOS',
            [
                ('▤  Modelos', 1),
                ('☆  Favoritos', 3),
                ('▰  Arquivados', 4),
            ],
        ),
        (
            'APLICATIVO',
            [
                ('⚙  Configurações', 5),
                ('?  Tutorial', 7),
            ],
        ),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setObjectName("sidebar")
        self.setFixedWidth(205)
        self.setSpacing(2)

        for section, entries in self.SECTIONS:
            heading = QListWidgetItem(section)
            heading.setFlags(Qt.ItemFlag.NoItemFlags)
            heading.setData(
                Qt.ItemDataRole.UserRole + 1,
                "section",
            )
            self.addItem(heading)

            for text, page_index in entries:
                item = QListWidgetItem(text)
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    page_index,
                )
                self.addItem(item)

        self.currentItemChanged.connect(
            self._current_item_changed
        )
        self.select_page(8)

    def _current_item_changed(
        self,
        current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return

        page_index = current.data(
            Qt.ItemDataRole.UserRole
        )

        if page_index is None:
            return

        self.page_changed.emit(
            int(page_index)
        )

    def select_page(
        self,
        page_index: int,
    ) -> None:
        for row in range(self.count()):
            item = self.item(row)

            if item.data(
                Qt.ItemDataRole.UserRole
            ) == page_index:
                self.setCurrentRow(row)
                return
