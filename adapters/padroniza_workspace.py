from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


PAGE_DESCRIPTIONS = {
    "home": "Visão geral do módulo, indicadores e atalhos rápidos.",
    "generate": "Escolha um modelo, preencha os dados e gere o documento.",
    "templates": "Organize a biblioteca de modelos e suas versões.",
    "recent": "Acesse o histórico recente de documentos gerados.",
    "favorites": "Abra rapidamente seus modelos favoritos.",
    "archive": "Consulte modelos arquivados e restaure quando necessário.",
    "converter": "Converta arquivos DOCX e PDF dentro do mesmo fluxo.",
    "settings": "Ajuste preferências, dados e comportamento do aplicativo.",
    "tutorial": "Aprenda o fluxo de uso e os recursos principais.",
}


class PadronizaWorkspaceWrapper(QWidget):
    """Office Tools presentation layer for the embedded Padroniza workspace.

    The original Padroniza UI keeps all business logic and page widgets intact.
    This wrapper removes the extra standalone chrome (menu + internal sidebar)
    and replaces it with an Office Tools-like hero and compact top navigation.
    """

    def __init__(self, workspace: QWidget) -> None:
        super().__init__()
        self.workspace = workspace
        self.workspace.setObjectName("PadronizaInnerWorkspace")
        self.setObjectName("PadronizaWorkspaceShell")
        self._page_keys = [
            "home",
            "generate",
            "templates",
            "recent",
            "favorites",
            "archive",
            "converter",
            "settings",
            "tutorial",
        ]
        self._nav_buttons: dict[str, QPushButton] = {}
        self._page_targets: dict[str, QWidget] = {
            "home": self.workspace.home_page,
            "generate": self.workspace.generate_page,
            "templates": self.workspace.templates_page,
            "recent": self.workspace.recent_page,
            "favorites": self.workspace.favorites_page,
            "archive": self.workspace.archive_page,
            "converter": self.workspace.converter_page,
            "settings": self.workspace.settings_page,
            "tutorial": self.workspace.tutorial_page,
        }

        self._prepare_inner_workspace()
        self._simplify_inner_pages()
        self._build_ui()
        self._apply_styles()
        self._sync_state()

    def _prepare_inner_workspace(self) -> None:
        self.workspace.menuBar().hide()
        self.workspace.sidebar.hide()
        self.workspace.setMinimumSize(0, 0)

    def _simplify_inner_pages(self) -> None:
        # The embedded wrapper already provides a module hero. Hide the
        # original Padroniza landing hero to avoid duplicated messaging.
        home_hero = self.workspace.home_page.findChild(QFrame, "homeHero")
        if home_hero is not None:
            home_hero.hide()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        root.addWidget(self._build_hero())
        root.addWidget(self._build_nav_bar())
        root.addWidget(self.workspace, 1)

        self.workspace.pages.currentChanged.connect(self._sync_state)

    def _build_hero(self) -> QWidget:
        hero = QFrame()
        hero.setObjectName("PadronizaHero")
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)

        text_column = QVBoxLayout()
        text_column.setSpacing(4)

        eyebrow = QLabel("PADRONIZA")
        eyebrow.setObjectName("PadronizaHeroEyebrow")

        title = QLabel("Documentos e modelos")
        title.setObjectName("PadronizaHeroTitle")

        subtitle = QLabel(
            "Agora com visual integrado ao Office Tools: um único fluxo para criar documentos, "
            "gerenciar modelos, acompanhar recentes e converter arquivos."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("PadronizaHeroSubtitle")

        self.context_label = QLabel("")
        self.context_label.setObjectName("PadronizaHeroContext")
        self.context_label.setWordWrap(True)

        text_column.addWidget(eyebrow)
        text_column.addWidget(title)
        text_column.addWidget(subtitle)
        text_column.addWidget(self.context_label)
        layout.addLayout(text_column, 1)

        actions = QVBoxLayout()
        actions.setSpacing(8)

        create_button = QPushButton("Criar documento")
        create_button.setProperty("heroRole", "primary")
        create_button.clicked.connect(lambda: self._navigate("generate"))

        models_button = QPushButton("Biblioteca de modelos")
        models_button.setProperty("heroRole", "secondary")
        models_button.clicked.connect(lambda: self._navigate("templates"))

        search_button = QPushButton("Pesquisar")
        search_button.setProperty("heroRole", "secondary")
        search_button.clicked.connect(self.workspace._show_global_search)

        actions.addWidget(create_button)
        actions.addWidget(models_button)
        actions.addWidget(search_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        return hero

    def _build_nav_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("PadronizaNavBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)

        nav_items = [
            ("home", "Início"),
            ("generate", "Gerar"),
            ("templates", "Modelos"),
            ("recent", "Recentes"),
            ("favorites", "Favoritos"),
            ("archive", "Arquivados"),
            ("converter", "Conversor"),
            ("settings", "Configurações"),
            ("tutorial", "Tutorial"),
        ]
        for key, text in nav_items:
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("padNav", True)
            button.clicked.connect(lambda checked=False, page=key: self._navigate(page))
            self.nav_group.addButton(button)
            self._nav_buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self.section_hint = QLabel("Selecione uma área")
        self.section_hint.setObjectName("PadronizaSectionHint")
        layout.addWidget(self.section_hint)
        return bar

    def _navigate(self, page_key: str) -> None:
        target = self._page_targets.get(page_key)
        if target is None:
            return
        index = self.workspace.pages.indexOf(target)
        if index < 0:
            return
        self.workspace.sidebar.select_page(index)
        self.workspace.pages.setCurrentIndex(index)
        self._sync_state()

    def _current_page_key(self) -> str:
        current = self.workspace.pages.currentWidget()
        for key, widget in self._page_targets.items():
            if widget is current:
                return key
        return "home"

    def _sync_state(self) -> None:
        key = self._current_page_key()
        button = self._nav_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        self.context_label.setText(PAGE_DESCRIPTIONS.get(key, ""))
        self.section_hint.setText(f"Área atual: {button.text() if button is not None else 'Início'}")

    def _apply_styles(self) -> None:
        wrapper_styles = """
            QWidget#PadronizaWorkspaceShell {
                background: #F4F6FA;
            }
            QFrame#PadronizaHero,
            QFrame#PadronizaNavBar {
                background: #FFFFFF;
                border: 1px solid #DEE5EF;
                border-radius: 16px;
            }
            QLabel#PadronizaHeroEyebrow {
                color: #6C7A91;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.08em;
            }
            QLabel#PadronizaHeroTitle {
                color: #1C2B44;
                font-size: 28px;
                font-weight: 700;
            }
            QLabel#PadronizaHeroSubtitle,
            QLabel#PadronizaHeroContext,
            QLabel#PadronizaSectionHint {
                color: #52637D;
                font-size: 13px;
            }
            QPushButton[heroRole="primary"] {
                background: #315FDB;
                color: #FFFFFF;
                border: 1px solid #315FDB;
                border-radius: 8px;
                padding: 9px 16px;
                font-size: 13px;
                font-weight: 600;
                min-height: 18px;
                min-width: 190px;
            }
            QPushButton[heroRole="primary"]:hover {
                background: #264FC3;
                border-color: #264FC3;
            }
            QPushButton[heroRole="secondary"] {
                background: #FFFFFF;
                color: #34445E;
                border: 1px solid #D4DBE7;
                border-radius: 8px;
                padding: 9px 16px;
                font-size: 13px;
                font-weight: 600;
                min-height: 18px;
                min-width: 190px;
            }
            QPushButton[heroRole="secondary"]:hover {
                background: #EFF4FF;
                border-color: #AFC2EA;
            }
            QPushButton[padNav="true"] {
                background: #FFFFFF;
                color: #34445E;
                border: 1px solid #D4DBE7;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 600;
                min-height: 18px;
            }
            QPushButton[padNav="true"]:hover {
                background: #EFF4FF;
                border-color: #AFC2EA;
            }
            QPushButton[padNav="true"]:checked {
                background: #315FDB;
                color: #FFFFFF;
                border-color: #315FDB;
            }
        """

        inner_overrides = """
            QMenuBar {
                max-height: 0px;
                min-height: 0px;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QListWidget#sidebar {
                max-width: 0px;
                min-width: 0px;
                border: none;
                padding: 0px;
                margin: 0px;
            }
            QWidget#PadronizaInnerWorkspace {
                background-color: #F4F6FA;
                color: #1F2937;
            }
            QLabel {
                color: #1F2937;
            }
            QLabel#homeEyebrow,
            QLabel#homeSectionHint,
            QLabel#homeMetricCaption,
            QLabel#homeActionText,
            QLabel#homeSubtitle,
            QLabel#mutedText,
            QLabel#draftResumeText,
            QLabel#assistedDetectionText {
                color: #52637D;
            }
            QLabel#homeTitle,
            QLabel#pageTitle,
            QLabel#templateTitle,
            QLabel#homeSectionTitle,
            QLabel#homeActionTitle,
            QLabel#homeMetricTitle,
            QLabel#draftResumeTitle,
            QLabel#assistedDetectionTitle {
                color: #1C2B44;
                font-weight: 700;
            }
            QLabel#homeMetricValue {
                color: #315FDB;
                font-size: 22px;
                font-weight: 700;
            }
            QFrame#homeHero,
            QFrame#homePanel,
            QFrame#homeMetricCard,
            QFrame#homeActionCard,
            QFrame#generateTemplateBar,
            QFrame#draftResumeBanner,
            QFrame#assistedDetectionBanner,
            QFrame#templateCard,
            QGroupBox,
            QFrame#selectorBar {
                background: #FFFFFF;
                border: 1px solid #DEE5EF;
                border-radius: 14px;
            }
            QGroupBox {
                margin-top: 14px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #34445E;
                background: #F4F6FA;
                font-weight: 600;
            }
            QPushButton,
            QComboBox,
            QLineEdit,
            QSpinBox,
            QDateEdit,
            QPlainTextEdit,
            QTableWidget,
            QListWidget,
            QScrollArea {
                background-color: #FFFFFF;
            }
            QLineEdit,
            QPlainTextEdit,
            QComboBox,
            QDateEdit,
            QSpinBox {
                border-radius: 8px;
                border: 1px solid #D4DBE7;
                padding: 8px 10px;
                color: #1F2937;
            }
            QLineEdit:hover,
            QPlainTextEdit:hover,
            QComboBox:hover,
            QDateEdit:hover,
            QSpinBox:hover {
                border-color: #B8C4D8;
            }
            QLineEdit:focus,
            QPlainTextEdit:focus,
            QComboBox:focus,
            QDateEdit:focus,
            QSpinBox:focus,
            QPushButton:focus {
                border: 1px solid #315FDB;
                outline: none;
            }
            QPushButton {
                border-radius: 8px;
                border: 1px solid #D4DBE7;
                padding: 8px 14px;
                color: #34445E;
                background: #FFFFFF;
            }
            QPushButton:hover {
                background: #EFF4FF;
                border-color: #AFC2EA;
            }
            QPushButton:disabled,
            QLineEdit:disabled,
            QPlainTextEdit:disabled,
            QComboBox:disabled,
            QSpinBox:disabled,
            QDateEdit:disabled {
                color: #8B98AD;
                background: #F7F9FC;
                border-color: #E2E8F0;
            }
            QPushButton#primaryButton {
                background: #315FDB;
                color: #FFFFFF;
                border-color: #315FDB;
            }
            QPushButton#primaryButton:hover {
                background: #264FC3;
                border-color: #264FC3;
            }
            QTableWidget {
                gridline-color: #E6ECF4;
                border: 1px solid #DDE5F0;
                border-radius: 10px;
                selection-background-color: #315FDB;
                selection-color: #FFFFFF;
            }
            QHeaderView::section {
                background: #1F2E45;
                color: #FFFFFF;
                padding: 8px 10px;
                border: none;
                border-right: 1px solid #2F4669;
                font-weight: 600;
            }
            QTableWidget::item {
                padding: 6px;
                color: #24344D;
            }
            QFrame#homeActionCard {
                background: #FFFFFF;
                border: 1px solid #DDE5F0;
                border-radius: 12px;
            }
            QFrame#homeActionCard:hover {
                background: #F8FAFD;
                border-color: #B8C8E2;
            }
            QPushButton#homeActionButton {
                background: transparent;
                border: none;
                padding: 4px 0;
                color: #315FDB;
                font-weight: 700;
                text-align: left;
            }
            QPushButton#homeActionButton:hover {
                background: transparent;
                border: none;
                color: #264FC3;
                text-decoration: none;
            }
            QFrame#homeMetricCard {
                background: #FFFFFF;
                border: 1px solid #DDE5F0;
                border-radius: 12px;
            }
            QFrame#homePanel {
                background: #FFFFFF;
                border: 1px solid #DDE5F0;
                border-radius: 14px;
            }
            QFrame#templateCreationHeader {
                background: #FFFFFF;
                border: 1px solid #DDE5F0;
                border-radius: 12px;
            }
            QFrame#templateCreationStep {
                background: #F8FAFD;
                border: 1px solid #DCE4EF;
                border-radius: 10px;
            }
            QFrame#templateCreationStep[stepState="current"] {
                background: #F3F7FF;
                border: 1px solid #AFC5EF;
            }
            QFrame#templateCreationStep[stepState="done"] {
                background: #F6FAF7;
                border: 1px solid #C6DDCD;
            }
            QFrame#templateDocxDropZone {
                background: #FAFCFF;
                border: 1px dashed #BBC8D8;
                border-radius: 12px;
            }
            QFrame#templateDocxDropZone:hover {
                background: #F6F9FE;
                border-color: #9CB2D1;
            }
            QFrame#templateDocxDropZone[dragActive="true"] {
                background: #EEF5FF;
                border-color: #779FE0;
            }
            QFrame#templateDocxDropZone[selected="true"] {
                background: #F5FAF7;
                border: 1px solid #AFCDB9;
            }
            QFrame#templateDocxDropZone[selected="true"]:hover {
                background: #F2F8F4;
                border-color: #96BEA3;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 10px;
                margin: 4px 2px 4px 2px;
            }
            QScrollBar::handle:vertical {
                background: #C8D2E0;
                min-height: 42px;
                border-radius: 4px;
            }
            QScrollBar::handle:vertical:hover {
                background: #AEBCCD;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
                border: none;
                background: transparent;
            }
            QScrollBar::add-page:vertical,
            QScrollBar::sub-page:vertical {
                background: transparent;
            }
            QScrollBar:horizontal {
                background: transparent;
                height: 10px;
                margin: 2px 4px 2px 4px;
            }
            QScrollBar::handle:horizontal {
                background: #C8D2E0;
                min-width: 42px;
                border-radius: 4px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #AEBCCD;
            }
            QScrollBar::add-line:horizontal,
            QScrollBar::sub-line:horizontal {
                width: 0px;
                border: none;
                background: transparent;
            }
            QScrollBar::add-page:horizontal,
            QScrollBar::sub-page:horizontal {
                background: transparent;
            }
            QScrollBar::corner {
                background: transparent;
            }
            QStatusBar {
                background: #FFFFFF;
                border-top: 1px solid #E5EAF2;
                color: #52637D;
            }
        """

        self.setStyleSheet(wrapper_styles)
        light_stylesheet_path = (
            self.workspace.theme_manager.project_root
            / "app"
            / "ui"
            / "styles"
            / "light.qss"
        )
        base_styles = (
            light_stylesheet_path.read_text(encoding="utf-8")
            if light_stylesheet_path.exists()
            else ""
        )
        self.workspace.setStyleSheet(base_styles + "\n" + inner_overrides)

    def can_leave(self) -> bool:
        hook = getattr(self.workspace, "can_leave", None)
        return True if hook is None else bool(hook())

    def can_close(self) -> bool:
        hook = getattr(self.workspace, "can_close", None)
        return True if hook is None else bool(hook())
