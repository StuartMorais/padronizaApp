from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent
from PySide6.QtWidgets import QBoxLayout, QFrame, QHBoxLayout, QVBoxLayout, QWidget

from shell.app_card import AppCard
from shell.catalog import MODULES
from shell.widgets import ScrollPage, button, icon_tile, label, page_heading


class HomeDashboard(ScrollPage):
    navigate_requested = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.body.addWidget(label("SEU ESPAÇO DE TRABALHO", "eyebrow"))
        self.body.addWidget(page_heading(
            "Ferramentas do Escritório",
            "Acesse as principais ferramentas em um só lugar.\n"
            "Mais agilidade, padronização e controle para o seu trabalho.",
        ))
        self.body.addSpacing(4)
        section = QHBoxLayout()
        section.addWidget(label("Aplicativos", "sectionTitle"))
        section.addStretch()
        section.addWidget(label("Selecione uma ferramenta para começar", "caption"))
        self.body.addLayout(section)

        cards_area = QWidget()
        self.cards_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, cards_area)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(22)
        self.cards = {}
        for spec in MODULES:
            card = AppCard(spec)
            card.open_requested.connect(self.navigate_requested)
            self.cards[spec.key] = card
            self.cards_layout.addWidget(card, 1)
        self.body.addWidget(cards_area)

        preferences = QFrame()
        preferences.setProperty("role", "settingsBanner")
        row = QHBoxLayout(preferences)
        row.setContentsMargins(22, 20, 22, 20)
        row.setSpacing(16)
        row.addWidget(icon_tile("settings", "#65758F", size=44))
        words = QVBoxLayout()
        words.setSpacing(5)
        words.addWidget(label("Personalize seu espaço", "sectionTitle"))
        words.addWidget(label("Escolha a tela inicial e as preferências da janela.", "caption", True))
        row.addLayout(words, 1)
        self.settings_button = button("Configurações   →")
        self.settings_button.clicked.connect(lambda: self.navigate_requested.emit("settings"))
        row.addWidget(self.settings_button)
        self.body.addWidget(preferences)

        footer = QHBoxLayout()
        footer.addWidget(label("PADRONIZA + CHECKLIST", "footer"))
        footer.addStretch()
        footer.addWidget(label("Um só lugar para organizar o trabalho.", "caption"))
        self.body.addLayout(footer)
        self.body.addStretch(1)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        direction = QBoxLayout.Direction.TopToBottom if self.viewport().width() < 800 else QBoxLayout.Direction.LeftToRight
        if direction != self.cards_layout.direction():
            self.cards_layout.setDirection(direction)
