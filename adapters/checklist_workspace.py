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

from adapters.contracts import WorkspaceContext
from checklist_app.theme import build_qss
from shell.design import palette
from shell.theme import normalize_theme
from checklist_app.main_window import CHECKLIST_PAGE, HOME_PAGE, SCANNER_PAGE


PAGE_INFO = {
    HOME_PAGE: ("Início", "Visão geral dos checklists e do fluxo de revisão."),
    CHECKLIST_PAGE: ("Checklists", "Revise, edite e organize os itens do checklist selecionado."),
    SCANNER_PAGE: ("Scanner", "Analise um documento e transforme sua estrutura em um checklist revisável."),
}


class ChecklistWorkspaceWrapper(QWidget):
    """Unified Nexo presentation layer for the Checklist module."""

    def __init__(self, workspace: QWidget, context: WorkspaceContext) -> None:
        super().__init__()
        self.workspace = workspace
        self.context = context
        self.theme = normalize_theme(context.get_theme())
        self.setObjectName("ChecklistWorkspaceShell")
        self.workspace.setObjectName("ChecklistInnerWorkspace")
        self._nav_buttons: dict[int, QPushButton] = {}

        self._prepare_inner_workspace()
        self._build_ui()
        self.set_theme(self.theme)
        self._sync_state()

    def _prepare_inner_workspace(self) -> None:
        # QMainWindow can safely live inside the wrapper when explicitly turned
        # into a child widget. Its business logic remains unchanged.
        self.workspace.setWindowFlags(Qt.WindowType.Widget)
        self.workspace.setMinimumSize(0, 0)

        workspace_bar = self.workspace.findChild(QFrame, "workspaceBar")
        if workspace_bar is not None:
            workspace_bar.hide()

        home_hero = self.workspace.findChild(QFrame, "homeHero")
        if home_hero is not None:
            home_hero.hide()

        # Runtime paths are useful for debugging but add visual noise to the
        # integrated library panel. Keep storage behavior unchanged, just hide
        # the technical path label in the normal Nexo workspace.
        for label in self.workspace.findChildren(QLabel):
            if label.text().startswith("Dados locais:"):
                label.hide()

        status_bar = self.workspace.statusBar()
        status_bar.removeWidget(self.workspace.status_label)
        status_bar.hide()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)

        self.hero = self._build_hero()
        self.nav_bar = self._build_nav_bar()
        self.status_strip = self._build_status_strip()
        root.addWidget(self.hero)
        root.addWidget(self.nav_bar)
        root.addWidget(self.workspace, 1)
        root.addWidget(self.status_strip)

        self.workspace.pages.currentChanged.connect(self._sync_state)

    def _build_hero(self) -> QFrame:
        hero = QFrame()
        hero.setObjectName("ChecklistHero")
        layout = QHBoxLayout(hero)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)

        text = QVBoxLayout()
        text.setSpacing(4)

        eyebrow = QLabel("CHECKLIST")
        eyebrow.setObjectName("ChecklistHeroEyebrow")
        title = QLabel("Revisão e conformidade")
        title.setObjectName("ChecklistHeroTitle")
        subtitle = QLabel(
            "Organize checklists, revise processos em uma folha estruturada e use o scanner "
            "para transformar documentos em listas de verificação."
        )
        subtitle.setObjectName("ChecklistHeroSubtitle")
        subtitle.setWordWrap(True)

        self.context_label = QLabel("")
        self.context_label.setObjectName("ChecklistHeroContext")
        self.context_label.setWordWrap(True)

        text.addWidget(eyebrow)
        text.addWidget(title)
        text.addWidget(subtitle)
        text.addWidget(self.context_label)
        layout.addLayout(text, 1)

        actions = QVBoxLayout()
        actions.setSpacing(8)

        new_button = QPushButton("Novo checklist")
        new_button.setProperty("heroRole", "primary")
        new_button.clicked.connect(self._create_checklist)

        scan_button = QPushButton("Abrir scanner")
        scan_button.setProperty("heroRole", "secondary")
        scan_button.clicked.connect(lambda: self._navigate(SCANNER_PAGE))

        pdf_button = QPushButton("Exportar PDF")
        pdf_button.setProperty("heroRole", "secondary")
        pdf_button.clicked.connect(self.workspace.export_pdf)

        actions.addWidget(new_button)
        actions.addWidget(scan_button)
        actions.addWidget(pdf_button)
        actions.addStretch(1)
        layout.addLayout(actions)
        return hero

    def _build_nav_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("ChecklistNavBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(10)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for page, label in (
            (HOME_PAGE, "Início"),
            (CHECKLIST_PAGE, "Checklists"),
            (SCANNER_PAGE, "Scanner"),
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setProperty("checkNav", True)
            button.clicked.connect(lambda checked=False, target=page: self._navigate(target))
            self.nav_group.addButton(button)
            self._nav_buttons[page] = button
            layout.addWidget(button)

        layout.addStretch(1)
        self.section_hint = QLabel("")
        self.section_hint.setObjectName("ChecklistSectionHint")
        layout.addWidget(self.section_hint)
        return bar

    def _build_status_strip(self) -> QFrame:
        strip = QFrame()
        strip.setObjectName("ChecklistStatusStrip")
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(14, 7, 14, 7)
        layout.setSpacing(8)
        layout.addWidget(self.workspace.status_label, 1)

        save = QPushButton("Salvar")
        save.setProperty("statusAction", True)
        save.clicked.connect(lambda: self.workspace.save_now(silent=False))
        layout.addWidget(save)
        return strip

    def _create_checklist(self) -> None:
        self.workspace.create_empty_checklist()
        self._navigate(CHECKLIST_PAGE)

    def _navigate(self, page: int) -> None:
        self.workspace.navigate_to(page)
        self._sync_state()

    def _sync_state(self) -> None:
        page = self.workspace.pages.currentIndex()
        if page not in PAGE_INFO:
            page = HOME_PAGE
        title, description = PAGE_INFO[page]
        button = self._nav_buttons.get(page)
        if button is not None:
            button.setChecked(True)
        self.context_label.setText(description)
        self.section_hint.setText(f"Área atual: {title}")

        # Home can afford the full marketing-style hero. Working pages need the
        # vertical space for the actual document/checklist content.
        if hasattr(self, "hero"):
            self.hero.setVisible(page == HOME_PAGE)
        if hasattr(self, "status_strip"):
            self.status_strip.setVisible(page != HOME_PAGE)

    def set_theme(self, theme: str) -> None:
        self.theme = normalize_theme(theme)
        p = palette(self.theme)
        teal = p["teal"]
        teal_hover = p["teal_hover"]
        button_text = "#0E1A19" if self.theme == "dark" else "#FFFFFF"

        wrapper_qss = f"""
            QWidget#ChecklistWorkspaceShell {{ background: {p['bg']}; color: {p['text']}; }}
            QFrame#ChecklistHero, QFrame#ChecklistNavBar, QFrame#ChecklistStatusStrip {{
                background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 16px;
            }}
            QFrame#ChecklistStatusStrip {{ border-radius: 10px; }}
            QLabel#ChecklistHeroEyebrow {{ color: {p['muted']}; font-size: 11px; font-weight: 700; }}
            QLabel#ChecklistHeroTitle {{ color: {p['title']}; font-size: 28px; font-weight: 700; }}
            QLabel#ChecklistHeroSubtitle, QLabel#ChecklistHeroContext, QLabel#ChecklistSectionHint {{
                color: {p['muted']}; font-size: 13px;
            }}
            QPushButton[heroRole="primary"] {{
                background: {teal}; color: {button_text}; border: 1px solid {teal}; border-radius: 8px;
                padding: 9px 16px; font-size: 13px; font-weight: 700; min-width: 190px;
            }}
            QPushButton[heroRole="primary"]:hover {{ background: {teal_hover}; border-color: {teal_hover}; }}
            QPushButton[heroRole="secondary"], QPushButton[statusAction="true"], QPushButton[checkNav="true"] {{
                background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']};
                border-radius: 8px; padding: 8px 14px; font-size: 12px; font-weight: 600;
            }}
            QPushButton[heroRole="secondary"] {{ padding: 9px 16px; font-size: 13px; min-width: 190px; }}
            QPushButton[statusAction="true"] {{ min-width: 76px; padding: 5px 12px; }}
            QPushButton[heroRole="secondary"]:hover, QPushButton[statusAction="true"]:hover, QPushButton[checkNav="true"]:hover {{
                background: {p['teal_soft']}; border-color: {p['teal_border']};
            }}
            QPushButton[checkNav="true"]:checked {{ background: {teal}; color: {button_text}; border-color: {teal}; }}
        """

        inner_qss = f"""
            QWidget#ChecklistInnerWorkspace {{ background: {p['bg']}; color: {p['text']}; }}
            QLabel {{ background: transparent; color: {p['text']}; }}
            QFrame#workspaceBar, QFrame#homeHero {{ max-height: 0px; min-height: 0px; border: none; }}
            QFrame#card, QFrame#panelCard, QFrame#templateHeader, QFrame#scannerHero, QFrame#paperPanel,
            QFrame#guidancePanel, QFrame#officialHeader {{
                background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 14px;
            }}
            QFrame#scannerHero {{ background: {p['teal_soft']}; border-color: {p['teal_border']}; }}
            QFrame#guidancePanel {{ background: {p['surface']}; }}
            QLabel#pageTitle, QLabel#sectionTitle, QLabel#officialTitle {{ color: {p['title']}; }}
            QLabel#mutedText {{ color: {p['muted']}; }}
            QLabel#metricValue {{ color: {teal}; }}
            QLabel#statusBadge {{ background: {p['surface_alt']}; color: {p['text']}; border: 1px solid {p['border']}; }}
            QLabel[inspectorLabel="true"] {{ color: {p['text']}; font-size: 12px; font-weight: 700; }}
            QLineEdit, QPlainTextEdit, QComboBox {{
                background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']};
                border-radius: 8px; padding: 8px 10px; selection-background-color: {teal}; selection-color: {button_text};
            }}
            QLineEdit:hover, QPlainTextEdit:hover, QComboBox:hover {{ border-color: {p['teal_border']}; }}
            QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 1px solid {teal}; }}
            QPushButton {{
                background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border_strong']};
                border-radius: 8px; padding: 7px 13px; font-weight: 600;
            }}
            QPushButton:hover {{ background: {p['teal_soft']}; border-color: {p['teal_border']}; }}
            QPushButton#primaryButton {{ background: {teal}; color: {button_text}; border-color: {teal}; }}
            QPushButton#primaryButton:hover {{ background: {teal_hover}; border-color: {teal_hover}; }}
            QPushButton#dangerButton {{ background: {p['surface']}; color: {p['danger']}; border-color: {p['danger']}; }}
            QPushButton#dangerButton:hover {{ background: {p['danger_soft']}; }}
            QPushButton:disabled, QLineEdit:disabled, QPlainTextEdit:disabled, QComboBox:disabled {{
                color: {p['disabled']}; background: {p['disabled_bg']}; border-color: {p['border']};
            }}
            QListWidget#libraryList {{
                background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px; padding: 6px; outline: 0;
            }}
            QListWidget#libraryList::item {{
                color: {p['text']}; border: 1px solid transparent; border-radius: 8px; padding: 10px 12px; margin: 0;
            }}
            QListWidget#libraryList::item:hover {{ background: {p['surface_alt']}; border-color: {p['border']}; }}
            QListWidget#libraryList::item:selected {{ background: {p['teal_soft']}; color: {teal}; border: 1px solid {p['teal_border']}; }}
            QListWidget#libraryList::item:selected:hover {{ background: {p['teal_soft']}; border-color: {p['teal_border']}; }}
            QTableWidget, QTableWidget#checklistSheetTable {{
                background: {p['surface']}; alternate-background-color: {p['surface_alt']}; color: {p['text']};
                border: 1px solid {p['border']}; border-radius: 10px; gridline-color: {p['border']};
                selection-background-color: {p['teal_soft']}; selection-color: {p['text']};
            }}
            QTableWidget::item, QTableWidget#checklistSheetTable::item {{ padding: 6px; border: none; }}
            QTableWidget::item:selected, QTableWidget#checklistSheetTable::item:selected {{ background: {p['teal_soft']}; color: {p['text']}; }}
            QHeaderView::section, QTableWidget#checklistSheetTable QHeaderView::section {{
                background: {p['table_header']}; color: {p['text']}; border: none; border-right: 1px solid {p['border']};
                border-bottom: 1px solid {p['border']}; padding: 8px; font-weight: 700;
            }}
            QSplitter#checklistBodySplitter::handle {{ background: transparent; width: 8px; }}
            QSplitter#checklistBodySplitter::handle:hover {{ background: {p['teal_soft']}; }}
            QFrame#sheetToolbar {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 10px; margin: 3px 2px; }}
            QScrollBar::handle:vertical {{ background: {p['scroll']}; min-height: 32px; border-radius: 4px; }}
            QScrollBar::handle:vertical:hover {{ background: {p['scroll_hover']}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
            QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 3px; }}
            QScrollBar::handle:horizontal {{ background: {p['scroll']}; min-width: 32px; border-radius: 4px; }}
            QScrollBar::handle:horizontal:hover {{ background: {p['scroll_hover']}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
            QScrollBar::corner {{ background: transparent; }}
        """

        self.setStyleSheet(wrapper_qss)
        self.workspace.current_theme = self.theme
        self.workspace.setStyleSheet(build_qss(self.theme) + "\n" + inner_qss)
        # Section row colors are assigned explicitly when the sheet is built, so
        # refresh after a theme change to keep the table consistent.
        if hasattr(self.workspace, "checklist_table"):
            self.workspace.refresh_checklist_sheet()

    def can_leave(self) -> bool:
        return True

    def can_close(self) -> bool:
        try:
            self.workspace.save_now(silent=True)
        except Exception:
            return False
        return True
