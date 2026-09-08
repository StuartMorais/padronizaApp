from __future__ import annotations

from PySide6.QtCore import Qt
from shell.design import palette
from shell.theme import normalize_theme

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
    """Nexo presentation layer for the embedded Padroniza workspace.

    The original Padroniza UI keeps all business logic and page widgets intact.
    This wrapper removes the extra standalone chrome (menu + internal sidebar)
    and replaces it with an Nexo-like hero and compact top navigation.
    """

    def __init__(self, workspace: QWidget, theme: str = "light") -> None:
        super().__init__()
        self.workspace = workspace
        self.theme = normalize_theme(theme)
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
        self.set_theme(self.theme)
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
            "Integrado ao Nexo: um único fluxo para criar documentos, "
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

    def set_theme(self, theme: str) -> None:
        self.theme = normalize_theme(theme)
        p = palette(self.theme)
        accent = p["accent"]
        accent_hover = p["accent_hover"]

        wrapper_styles = f"""
            QWidget#PadronizaWorkspaceShell {{ background: {p['bg']}; color: {p['text']}; }}
            QFrame#PadronizaHero, QFrame#PadronizaNavBar {{
                background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 16px;
            }}
            QLabel#PadronizaHeroEyebrow {{ color: {p['muted']}; font-size: 11px; font-weight: 700; }}
            QLabel#PadronizaHeroTitle {{ color: {p['title']}; font-size: 28px; font-weight: 700; }}
            QLabel#PadronizaHeroSubtitle, QLabel#PadronizaHeroContext, QLabel#PadronizaSectionHint {{
                color: {p['muted']}; font-size: 13px;
            }}
            QPushButton[heroRole="primary"] {{
                background: {accent}; color: {'#101525' if self.theme == 'dark' else '#FFFFFF'};
                border: 1px solid {accent}; border-radius: 8px; padding: 9px 16px;
                font-size: 13px; font-weight: 700; min-width: 190px;
            }}
            QPushButton[heroRole="primary"]:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
            QPushButton[heroRole="secondary"], QPushButton[padNav="true"] {{
                background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']};
                border-radius: 8px; padding: 8px 14px; font-size: 12px; font-weight: 600;
            }}
            QPushButton[heroRole="secondary"] {{ min-width: 190px; padding: 9px 16px; font-size: 13px; }}
            QPushButton[heroRole="secondary"]:hover, QPushButton[padNav="true"]:hover {{
                background: {p['accent_soft']}; border-color: {p['accent_border']};
            }}
            QPushButton[padNav="true"]:checked {{
                background: {accent}; color: {'#101525' if self.theme == 'dark' else '#FFFFFF'}; border-color: {accent};
            }}
        """

        inner_overrides = f"""
            QMenuBar {{ max-height: 0px; min-height: 0px; border: none; padding: 0; margin: 0; }}
            QListWidget#sidebar {{ max-width: 0px; min-width: 0px; border: none; padding: 0; margin: 0; }}
            QWidget#PadronizaInnerWorkspace {{ background: {p['bg']}; color: {p['text']}; }}
            QLabel {{ background: transparent; color: {p['text']}; }}
            QLabel#homeEyebrow, QLabel#homeSectionHint, QLabel#homeMetricCaption, QLabel#homeActionText,
            QLabel#homeSubtitle, QLabel#mutedText, QLabel#draftResumeText, QLabel#assistedDetectionText {{ color: {p['muted']}; }}
            QLabel#homeTitle, QLabel#pageTitle, QLabel#templateTitle, QLabel#homeSectionTitle,
            QLabel#homeActionTitle, QLabel#homeMetricTitle, QLabel#draftResumeTitle, QLabel#assistedDetectionTitle {{
                color: {p['title']}; font-weight: 700;
            }}
            QLabel#homeMetricValue {{ color: {accent}; font-size: 22px; font-weight: 700; }}
            QFrame#homeHero, QFrame#homePanel, QFrame#homeMetricCard, QFrame#homeActionCard,
            QFrame#generateTemplateBar, QFrame#draftResumeBanner, QFrame#assistedDetectionBanner,
            QFrame#templateCard, QGroupBox, QFrame#selectorBar, QFrame#templateCreationHeader {{
                background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 14px;
            }}
            QFrame#homeActionCard:hover {{ background: {p['surface_alt']}; border-color: {p['accent_border']}; }}
            QGroupBox {{ margin-top: 14px; padding-top: 10px; }}
            QGroupBox::title {{
                subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {p['text']};
                background: {p['bg']}; font-weight: 600;
            }}
            QLineEdit, QPlainTextEdit, QComboBox, QDateEdit, QSpinBox {{
                background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']};
                border-radius: 8px; padding: 8px 10px; selection-background-color: {accent};
                selection-color: {'#101525' if self.theme == 'dark' else '#FFFFFF'};
            }}
            QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QDateEdit:hover, QSpinBox:hover {{ border-color: {p['accent_border']}; }}
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateEdit:focus, QSpinBox:focus, QPushButton:focus {{ border: 1px solid {accent}; }}
            QPushButton {{
                background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']};
                border-radius: 8px; padding: 8px 14px;
            }}
            QPushButton:hover {{ background: {p['accent_soft']}; border-color: {p['accent_border']}; }}
            QPushButton:disabled, QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDateEdit:disabled {{
                color: {p['disabled']}; background: {p['disabled_bg']}; border-color: {p['border']};
            }}
            QPushButton#primaryButton {{ background: {accent}; color: {'#101525' if self.theme == 'dark' else '#FFFFFF'}; border-color: {accent}; }}
            QPushButton#primaryButton:hover {{ background: {accent_hover}; border-color: {accent_hover}; }}
            QPushButton#homeActionButton {{ background: transparent; border: none; color: {accent}; text-align: left; font-weight: 700; }}
            QPushButton#homeActionButton:hover {{ background: transparent; border: none; color: {accent_hover}; }}
            QTableWidget {{
                background: {p['surface']}; color: {p['text']}; gridline-color: {p['border']};
                border: 1px solid {p['border']}; border-radius: 10px; selection-background-color: {p['accent_soft']};
                selection-color: {p['text']};
            }}
            QHeaderView::section {{
                background: {p['table_header']}; color: {p['text']}; padding: 8px 10px; border: none;
                border-right: 1px solid {p['border']}; border-bottom: 1px solid {p['border']}; font-weight: 700;
            }}
            QTableWidget::item {{ padding: 6px; color: {p['text']}; }}
            QFrame#templateCreationStep {{ background: {p['surface_alt']}; border: 1px solid {p['border']}; border-radius: 10px; }}
            QFrame#templateCreationStep[stepState="current"] {{ background: {p['accent_soft']}; border-color: {p['accent_border']}; }}
            QFrame#templateCreationStep[stepState="done"] {{ background: {p['teal_soft']}; border-color: {p['teal_border']}; }}
            QFrame#templateDocxDropZone {{ background: {p['surface_alt']}; border: 1px dashed {p['border_strong']}; border-radius: 12px; }}
            QFrame#templateDocxDropZone:hover {{ background: {p['accent_soft']}; border-color: {p['accent_border']}; }}
            QFrame#templateDocxDropZone[dragActive="true"] {{ background: {p['accent_soft']}; border-color: {accent}; }}
            QFrame#templateDocxDropZone[selected="true"] {{ background: {p['teal_soft']}; border: 1px solid {p['teal_border']}; }}
            QScrollArea {{ border: none; background: transparent; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
            QScrollBar::handle:vertical {{ background: {p['scroll']}; min-height: 42px; border-radius: 4px; }}
            QScrollBar::handle:vertical:hover {{ background: {p['scroll_hover']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; background: transparent; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
            QScrollBar::handle:horizontal {{ background: {p['scroll']}; min-width: 42px; border-radius: 4px; }}
            QScrollBar::handle:horizontal:hover {{ background: {p['scroll_hover']}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; border: none; background: transparent; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
            QScrollBar::corner {{ background: transparent; }}
            QStatusBar {{ background: {p['surface']}; border-top: 1px solid {p['border']}; color: {p['muted']}; }}
        """

        self.setStyleSheet(wrapper_styles)
        base_stylesheet_path = (
            self.workspace.theme_manager.project_root / "app" / "ui" / "styles" / f"{self.theme}.qss"
        )
        base_styles = base_stylesheet_path.read_text(encoding="utf-8") if base_stylesheet_path.exists() else ""
        self.workspace.setStyleSheet(base_styles + "\n" + inner_overrides)
        theme_combo = getattr(self.workspace, "theme_combo", None)
        if theme_combo is not None:
            index = theme_combo.findData(self.theme)
            theme_combo.blockSignals(True)
            theme_combo.setCurrentIndex(max(index, 0))
            theme_combo.blockSignals(False)

    def can_leave(self) -> bool:
        hook = getattr(self.workspace, "can_leave", None)
        return True if hook is None else bool(hook())

    def can_close(self) -> bool:
        hook = getattr(self.workspace, "can_close", None)
        return True if hook is None else bool(hook())
