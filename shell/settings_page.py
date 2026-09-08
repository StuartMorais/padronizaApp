from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QWidget

from shell.catalog import PAGE_TITLES
from shell.preferences import Preferences, START_PAGES
from shell.widgets import ScrollPage, button, label, page_heading, panel


class SettingsPage(ScrollPage):
    preferences_saved = Signal()

    def __init__(self, preferences: Preferences) -> None:
        super().__init__()
        self.preferences = preferences
        self.body.addWidget(page_heading("Configurações", "Deixe o Office Tools pronto para a sua rotina."))
        frame, layout = panel()
        layout.addWidget(label("Ao iniciar", "sectionTitle"))
        title = label("Tela de abertura")
        layout.addWidget(title)
        self.start_combo = QComboBox()
        self.start_combo.setObjectName("startPageCombo")
        self.start_combo.setAccessibleName("Tela de abertura")
        self.start_combo.setMinimumHeight(42)
        for page in START_PAGES:
            self.start_combo.addItem(PAGE_TITLES[page], page)
        self.start_combo.setCurrentIndex(self.start_combo.findData(preferences.start_page))
        title.setBuddy(self.start_combo)
        layout.addWidget(self.start_combo)
        layout.addWidget(label("Essa tela será exibida na próxima vez que você abrir o programa.", "caption", True))
        self.remember_check = QCheckBox("Lembrar tamanho e posição da janela")
        self.remember_check.setObjectName("rememberWindow")
        self.remember_check.setChecked(preferences.remember_window)
        layout.addSpacing(8)
        layout.addWidget(self.remember_check)
        layout.addWidget(label("As preferências são salvas para o seu usuário neste computador.", "caption", True))
        self.body.addWidget(frame)

        appearance, appearance_layout = panel()
        appearance_layout.addWidget(label("Aparência", "sectionTitle"))
        appearance_layout.addWidget(label("Tema claro", "body"))
        appearance_layout.addWidget(label("Uma interface clara, com navegação lateral e cartões de acesso rápido.", "muted", True))
        self.body.addWidget(appearance)

        actions = QHBoxLayout()
        self.status_label = label("", "success", True)
        self.status_label.setAccessibleName("Status das preferências")
        actions.addWidget(self.status_label, 1)
        self.save_button = button("Salvar preferências", "primary")
        self.save_button.clicked.connect(self.save)
        actions.addWidget(self.save_button)
        self.body.addLayout(actions)
        self.start_combo.currentIndexChanged.connect(self._edited)
        self.remember_check.toggled.connect(self._edited)
        self.body.addStretch(1)

    def _edited(self, *args) -> None:
        self.status_label.clear()

    def save(self) -> None:
        saved = self.preferences.save(self.start_combo.currentData(), self.remember_check.isChecked())
        self.status_label.setText("Preferências salvas." if saved else "Não foi possível salvar. Verifique as permissões do seu usuário.")
        self.status_label.setProperty("role", "success" if saved else "error")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        if saved:
            self.preferences_saved.emit()
