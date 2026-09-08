from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QColor, QFont, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .pdf_exporter import export_checklist_pdf
from .resources import resource_path
from .scanner import ScanResult, analyze_document, build_template_from_scan
from .scanner_dialogs import ScanDiagnosticsDialog, ScanReportDialog, ScanReviewDialog
from .storage import (
    BACKUP_DIR,
    DATA_FILE,
    export_checklist_json,
    import_checklists_json,
    load_templates,
    new_id,
    save_templates,
)
from .theme import apply_theme, get_saved_theme, save_theme

HOME_PAGE = 0
CHECKLIST_PAGE = 1
SCANNER_PAGE = 2

CHECKLIST_COLUMNS = [
    "Item",
    "Documento / Informações constantes do processo",
    "Normativo",
    "S / N / NA",
    "Folha",
    "Observação",
]

ITEM_FIELD_BY_COLUMN = {
    0: "number",
    1: "documento",
    2: "normativo",
    3: "situacao",
    4: "folha",
    5: "observacao",
}


class ChecklistMainWindow(QMainWindow):
    """Checklist manager with an official-checklist sheet view.

    The main checklist page intentionally mixes three ideas:
    - the original app's direct checklist/table workflow;
    - Padroniza's clearer workspace navigation and review-first organization;
    - the visual structure of the real checklist PDFs, where section bars and a
      verification table are the primary way to read the document.
    """

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("Checklist Application — Python")
        self.resize(1500, 900)
        self.setMinimumSize(1160, 740)

        icon_path = resource_path("assets/icon.ico")

        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.templates: list[dict[str, Any]] = []
        self.active_checklist_id: str | None = None
        self.active_section_index = 0
        self.active_item_index = -1
        self.pending_delete_key: str | None = None
        self.checklist_row_map: list[dict[str, int | str]] = []
        self.loading_controls = False
        self.loading_table = False
        self.startup_error = ""
        self.current_theme = get_saved_theme()
        self.expanded_section_ids: set[str] = set()
        self.last_scan_result: ScanResult | None = None

        self.load_data()
        self.build_ui()
        self.refresh_all()

        if self.templates:
            self.select_checklist(str(self.templates[0]["id"]))
        else:
            self.show_empty_state()

        if self.startup_error:
            self.show_status(f"Erro ao carregar JSON: {self.startup_error}")
        else:
            self.show_status("Pronto.")

    # ------------------------------------------------------------------ setup
    def load_data(self) -> None:
        try:
            self.templates = load_templates()
        except Exception as error:
            self.templates = []
            self.startup_error = str(error)

    def build_ui(self) -> None:
        self.pages = QStackedWidget()
        self.pages.addWidget(self.create_home_page())
        self.pages.addWidget(self.create_checklist_page())
        self.pages.addWidget(self.create_scanner_page())

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self.create_workspace_bar())
        root_layout.addWidget(self.pages, 1)

        self.setCentralWidget(root)
        self.create_statusbar_message()
        self.navigate_to(CHECKLIST_PAGE)
        self.update_theme_button()

    def create_statusbar_message(self) -> None:
        self.status_label = QLabel("Pronto")
        self.status_label.setObjectName("mutedText")
        self.statusBar().addPermanentWidget(self.status_label)

    def configure_list_widget(self, widget: QListWidget) -> None:
        """Apply readable lists with small pixel-based wheel movement.

        Qt item views normally scroll one whole item per wheel step. That feels
        abrupt when a checklist entry is tall. ScrollPerPixel keeps the wheel
        movement consistent regardless of item height.
        """
        widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        widget.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        widget.setSpacing(6)
        widget.verticalScrollBar().setSingleStep(14)
        widget.verticalScrollBar().setPageStep(120)
        widget.setWordWrap(True)
        widget.setTextElideMode(Qt.TextElideMode.ElideRight)
        widget.setUniformItemSizes(False)

    def configure_scroll_area(self, scroll: QScrollArea) -> None:
        """Reduce the wheel distance for normal page scroll areas."""
        scroll.verticalScrollBar().setSingleStep(18)
        scroll.horizontalScrollBar().setSingleStep(18)

    def configure_text_editor(self, editor: QPlainTextEdit, height: int) -> None:
        """Configure multiline editors with calmer pixel scrolling."""
        editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        editor.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        editor.verticalScrollBar().setSingleStep(12)
        editor.setMinimumHeight(height)
        editor.setFixedHeight(height)
        editor.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def create_workspace_bar(self) -> QFrame:
        """Create the single top navigation/workspace bar.

        The previous build had a permanent navigation sidebar plus the checklist
        library sidebar. This bar moves the "Área de trabalho" navigation to
        the top so the checklist library is the only left-side panel.
        """
        bar = QFrame()
        bar.setObjectName("workspaceBar")

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        brand = QLabel("CHECKLIST APPLICATION")
        brand.setObjectName("workspaceBrand")
        layout.addWidget(brand)

        area_label = QLabel("ÁREA DE TRABALHO")
        area_label.setObjectName("workspaceLabel")
        layout.addWidget(area_label)

        self.workspace_nav_group = QButtonGroup(self)
        self.workspace_nav_group.setExclusive(True)
        self.workspace_nav_buttons: dict[int, QPushButton] = {}

        for text, page in [
            ("Início", HOME_PAGE),
            ("Checklists", CHECKLIST_PAGE),
            ("Scanner", SCANNER_PAGE),
        ]:
            button = QPushButton(text)
            button.setObjectName("workspaceNavButton")
            button.setCheckable(True)
            if page == SCANNER_PAGE:
                button.clicked.connect(self.open_scanner_workspace)
            else:
                button.clicked.connect(lambda _checked=False, target=page: self.navigate_to(target))
            self.workspace_nav_group.addButton(button)
            self.workspace_nav_buttons[page] = button
            layout.addWidget(button)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setObjectName("workspaceSeparator")
        layout.addWidget(separator)

        new_button = QPushButton("Novo checklist")
        new_button.clicked.connect(self.create_empty_checklist)
        layout.addWidget(new_button)

        copy_button = QPushButton("Copiar")
        copy_button.clicked.connect(self.copy_active_checklist)
        layout.addWidget(copy_button)

        pdf_button = QPushButton("Exportar PDF")
        pdf_button.clicked.connect(self.export_pdf)
        layout.addWidget(pdf_button)

        json_button = QPushButton("JSON ▾")
        json_menu = QMenu(json_button)
        import_json_action = QAction("Importar checklist JSON…", self)
        import_json_action.triggered.connect(self.import_checklist_json)
        export_json_action = QAction("Exportar checklist ativo…", self)
        export_json_action.triggered.connect(self.export_active_checklist_json)
        json_menu.addAction(import_json_action)
        json_menu.addAction(export_json_action)
        json_button.setMenu(json_menu)
        layout.addWidget(json_button)

        save_button = QPushButton("Salvar")
        save_button.clicked.connect(lambda: self.save_now(silent=False))
        layout.addWidget(save_button)

        layout.addStretch(1)

        self.btn_theme = QPushButton("Modo escuro")
        self.btn_theme.setObjectName("themeButton")
        self.btn_theme.clicked.connect(self.toggle_theme)
        layout.addWidget(self.btn_theme)

        return bar

    def navigate_to(self, page: int) -> None:
        if not hasattr(self, "pages"):
            return

        page = page if page in {HOME_PAGE, CHECKLIST_PAGE, SCANNER_PAGE} else HOME_PAGE
        self.pages.setCurrentIndex(page)
        self.sync_workspace_navigation()

    def open_scanner_workspace(self, _checked: bool = False) -> None:
        """Open the single canonical scanner workspace.

        All scanner entry points use this method so the top navigation and the
        checklist library cannot drift into two different scan experiences.
        The actual file picker remains behind the page's "Analisar documento"
        button, matching Padroniza's review-first workflow.
        """
        self.navigate_to(SCANNER_PAGE)
        if hasattr(self, "btn_scan_page"):
            self.btn_scan_page.setFocus(Qt.FocusReason.OtherFocusReason)

    def sync_workspace_navigation(self) -> None:
        if not hasattr(self, "workspace_nav_buttons") or not hasattr(self, "pages"):
            return

        current_page = self.pages.currentIndex()

        for page, button in self.workspace_nav_buttons.items():
            button.blockSignals(True)
            button.setChecked(page == current_page)
            button.blockSignals(False)

    def toggle_theme(self) -> None:
        app = QApplication.instance()

        if app is None:
            return

        next_theme = "dark" if self.current_theme == "light" else "light"
        self.current_theme = apply_theme(app, next_theme)
        save_theme(self.current_theme)
        self.update_theme_button()
        self.refresh_checklist_sheet()
        self.show_status("Modo escuro ativado." if self.current_theme == "dark" else "Modo claro ativado.")

    def update_theme_button(self) -> None:
        if not hasattr(self, "btn_theme"):
            return

        self.btn_theme.setText("Modo claro" if self.current_theme == "dark" else "Modo escuro")

    def section_row_color(self) -> str:
        return "#243244" if self.current_theme == "dark" else "#d9dde3"

    def code_accent_color(self) -> str:
        return "#7db7ff" if self.current_theme == "dark" else "#0f62b8"

    # --------------------------------------------------------------- home page
    def create_home_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.configure_scroll_area(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 26)
        layout.setSpacing(18)

        hero = QFrame()
        hero.setObjectName("homeHero")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        hero_layout.setSpacing(18)

        hero_text = QVBoxLayout()
        hero_text.setSpacing(6)

        eyebrow = QLabel("CHECKLIST APPLICATION")
        eyebrow.setObjectName("statusBadge")
        eyebrow.setMaximumWidth(190)

        title = QLabel("Bem-vindo")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "Gerencie checklists em um fluxo misto: navegação limpa estilo Padroniza, "
            "mas leitura principal no formato de folha de verificação oficial."
        )
        subtitle.setObjectName("mutedText")
        subtitle.setWordWrap(True)

        hero_text.addWidget(eyebrow)
        hero_text.addWidget(title)
        hero_text.addWidget(subtitle)
        hero_layout.addLayout(hero_text, 1)

        hero_actions = QVBoxLayout()
        hero_actions.setSpacing(8)

        open_button = QPushButton("Abrir checklists")
        open_button.setObjectName("primaryButton")
        open_button.clicked.connect(lambda: self.navigate_to(CHECKLIST_PAGE))

        scan_button = QPushButton("Escanear documento")
        scan_button.clicked.connect(self.open_scanner_workspace)

        pdf_button = QPushButton("Exportar PDF completo")
        pdf_button.clicked.connect(self.export_pdf)

        hero_actions.addWidget(open_button)
        hero_actions.addWidget(scan_button)
        hero_actions.addWidget(pdf_button)
        hero_actions.addStretch()
        hero_layout.addLayout(hero_actions)

        layout.addWidget(hero)

        metrics = QGridLayout()
        metrics.setHorizontalSpacing(12)
        metrics.setVerticalSpacing(12)

        self.metric_checklists = self.create_metric_card("0", "Checklists", "Modelos locais disponíveis")
        self.metric_sections = self.create_metric_card("0", "Seções", "Blocos estruturais")
        self.metric_items = self.create_metric_card("0", "Itens", "Documentos / informações")
        self.metric_active = self.create_metric_card("Nenhum", "Ativo", "Checklist selecionado")

        metrics.addWidget(self.metric_checklists, 0, 0)
        metrics.addWidget(self.metric_sections, 0, 1)
        metrics.addWidget(self.metric_items, 0, 2)
        metrics.addWidget(self.metric_active, 0, 3)
        layout.addLayout(metrics)

        workflow = QFrame()
        workflow.setObjectName("panelCard")
        workflow_layout = QVBoxLayout(workflow)
        workflow_layout.setContentsMargins(18, 16, 18, 16)
        workflow_layout.setSpacing(8)

        workflow_title = QLabel("Fluxo recomendado")
        workflow_title.setObjectName("sectionTitle")
        workflow_text = QLabel(
            "1. Selecione ou escaneie um checklist.\n"
            "2. Leia a folha principal por seção, como no PDF oficial.\n"
            "3. Edite situação, folha e observação diretamente na linha.\n"
            "4. Selecione um item para revisar os documentos mínimos no painel inferior."
        )
        workflow_text.setObjectName("mutedText")
        workflow_text.setWordWrap(True)

        workflow_layout.addWidget(workflow_title)
        workflow_layout.addWidget(workflow_text)
        layout.addWidget(workflow)
        layout.addStretch()

        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        return page

    def create_metric_card(self, value: str, label: str, helper: str) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setMinimumHeight(106)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(3)

        value_label = QLabel(value)
        value_label.setObjectName("metricValue")
        value_label.setWordWrap(True)

        label_widget = QLabel(label)
        label_widget.setObjectName("metricLabel")

        helper_widget = QLabel(helper)
        helper_widget.setObjectName("mutedText")
        helper_widget.setWordWrap(True)

        card.value_label = value_label  # type: ignore[attr-defined]

        layout.addWidget(value_label)
        layout.addWidget(label_widget)
        layout.addWidget(helper_widget)
        layout.addStretch()

        return card

    # ---------------------------------------------------------- checklist page
    def create_checklist_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(14, 14, 14, 14)
        page_layout.setSpacing(10)

        page_layout.addWidget(self.create_checklist_header())

        # Three-pane working layout:
        # library | verification sheet | selected-item inspector.
        # The old bottom inspector consumed most of the vertical space and left
        # the table showing only one or two rows. Keeping the inspector at the
        # side makes the checklist itself the primary surface.
        self.body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body_splitter.setObjectName("checklistBodySplitter")
        self.body_splitter.setChildrenCollapsible(False)

        library = self.create_library_panel()
        sheet = self.create_checklist_sheet_panel()
        inspector = self.create_selected_item_panel()

        self.body_splitter.addWidget(library)
        self.body_splitter.addWidget(sheet)
        self.body_splitter.addWidget(inspector)
        self.body_splitter.setStretchFactor(0, 0)
        self.body_splitter.setStretchFactor(1, 1)
        self.body_splitter.setStretchFactor(2, 0)
        self.body_splitter.setSizes([245, 920, 365])

        page_layout.addWidget(self.body_splitter, 1)
        return page

    def create_checklist_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("templateHeader")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(10)

        title_block = QVBoxLayout()
        title_block.setSpacing(2)
        self.checklist_title_display = QLabel("Checklist")
        self.checklist_title_display.setObjectName("pageTitle")
        self.checklist_subtitle_display = QLabel("Selecione um checklist")
        self.checklist_subtitle_display.setObjectName("mutedText")
        self.checklist_subtitle_display.setWordWrap(True)
        title_block.addWidget(self.checklist_title_display)
        title_block.addWidget(self.checklist_subtitle_display)

        self.active_badge = QLabel("Nenhum ativo")
        self.active_badge.setObjectName("statusBadge")

        top_row.addLayout(title_block, 1)
        top_row.addWidget(self.active_badge)
        layout.addLayout(top_row)

        form_row = QGridLayout()
        form_row.setHorizontalSpacing(8)
        form_row.setVerticalSpacing(4)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("Nome do checklist")
        self.subtitle_input = QLineEdit()
        self.subtitle_input.setPlaceholderText("Subtítulo")
        self.base_legal_input = QLineEdit()
        self.base_legal_input.setPlaceholderText("Base legal")

        self.btn_save_metadata = QPushButton("Salvar dados")
        self.btn_save_metadata.setObjectName("primaryButton")
        self.btn_save_metadata.clicked.connect(self.save_metadata)

        form_row.addWidget(QLabel("Nome"), 0, 0)
        form_row.addWidget(self.title_input, 0, 1)
        form_row.addWidget(QLabel("Subtítulo"), 0, 2)
        form_row.addWidget(self.subtitle_input, 0, 3)
        form_row.addWidget(QLabel("Base legal"), 0, 4)
        form_row.addWidget(self.base_legal_input, 0, 5)
        form_row.addWidget(self.btn_save_metadata, 0, 6)

        form_row.setColumnStretch(1, 2)
        form_row.setColumnStretch(3, 2)
        form_row.setColumnStretch(5, 3)
        layout.addLayout(form_row)
        return header

    def create_library_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("panelCard")
        panel.setMinimumWidth(220)
        panel.setMaximumWidth(275)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title = QLabel("Checklists")
        title.setObjectName("sectionTitle")

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Pesquisar checklist...")
        self.search_input.textChanged.connect(self.refresh_checklist_list)

        self.checklist_list = QListWidget()
        self.checklist_list.setObjectName("libraryList")
        self.configure_list_widget(self.checklist_list)
        self.checklist_list.currentItemChanged.connect(self.on_checklist_selection_changed)

        self.btn_scan = QPushButton("Abrir scanner")
        self.btn_scan.setObjectName("primaryButton")
        self.btn_scan.clicked.connect(self.open_scanner_workspace)

        self.btn_new = QPushButton("Novo vazio")
        self.btn_new.clicked.connect(self.create_empty_checklist)

        self.btn_copy = QPushButton("Copiar")
        self.btn_copy.clicked.connect(self.copy_active_checklist)

        self.btn_delete_checklist = QPushButton("Excluir checklist")
        self.btn_delete_checklist.setObjectName("dangerButton")
        self.btn_delete_checklist.clicked.connect(self.delete_active_checklist)

        self.btn_json = QPushButton("Importar / Exportar JSON ▾")
        json_menu = QMenu(self.btn_json)
        import_json_action = QAction("Importar checklist JSON…", self)
        import_json_action.triggered.connect(self.import_checklist_json)
        export_json_action = QAction("Exportar checklist ativo…", self)
        export_json_action.triggered.connect(self.export_active_checklist_json)
        json_menu.addAction(import_json_action)
        json_menu.addAction(export_json_action)
        self.btn_json.setMenu(json_menu)

        actions = QGridLayout()
        actions.setHorizontalSpacing(6)
        actions.setVerticalSpacing(6)
        actions.addWidget(self.btn_scan, 0, 0, 1, 2)
        actions.addWidget(self.btn_new, 1, 0)
        actions.addWidget(self.btn_copy, 1, 1)
        actions.addWidget(self.btn_json, 2, 0, 1, 2)
        actions.addWidget(self.btn_delete_checklist, 3, 0, 1, 2)

        path_label = QLabel(f"Dados locais:\n{DATA_FILE}\n\nBackups:\n{BACKUP_DIR}")
        path_label.setObjectName("mutedText")
        path_label.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(self.search_input)
        layout.addWidget(self.checklist_list, 1)
        layout.addLayout(actions)
        layout.addWidget(path_label)
        return panel

    def create_checklist_sheet_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("paperPanel")
        panel.setMinimumWidth(540)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        heading = QFrame()
        heading.setObjectName("officialHeader")
        heading_layout = QGridLayout(heading)
        heading_layout.setContentsMargins(12, 8, 12, 8)
        heading_layout.setHorizontalSpacing(10)
        heading_layout.setVerticalSpacing(2)

        self.sheet_title = QLabel("FOLHA DE VERIFICAÇÃO DE DOCUMENTOS")
        self.sheet_title.setObjectName("officialTitle")
        self.sheet_subtitle = QLabel("Checklist selecionado")
        self.sheet_subtitle.setObjectName("officialSubtitle")
        self.sheet_counts = QLabel("0 seção(ões) · 0 item(ns)")
        self.sheet_counts.setObjectName("statusBadge")

        heading_layout.addWidget(self.sheet_title, 0, 0, 1, 2)
        heading_layout.addWidget(self.sheet_subtitle, 1, 0)
        heading_layout.addWidget(
            self.sheet_counts, 0, 2, 2, 1,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        heading_layout.setColumnStretch(0, 1)
        layout.addWidget(heading)

        self.sheet_search_input = QLineEdit()
        self.sheet_search_input.setPlaceholderText(
            "Pesquisar item, documento, normativo, situação, folha ou observação..."
        )
        self.sheet_search_input.textChanged.connect(self.refresh_checklist_sheet)
        layout.addWidget(self.sheet_search_input)

        tools_panel = QFrame()
        tools_panel.setObjectName("sheetToolbar")
        tools = QGridLayout(tools_panel)
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setHorizontalSpacing(6)
        tools.setVerticalSpacing(6)

        self.btn_add_section = QPushButton("+ Seção")
        self.btn_add_section.clicked.connect(self.add_section)
        self.btn_rename_section = QPushButton("Renomear seção")
        self.btn_rename_section.clicked.connect(self.rename_section)
        self.btn_add_item = QPushButton("+ Item")
        self.btn_add_item.clicked.connect(self.add_item)
        self.btn_delete_section = QPushButton("Excluir seção")
        self.btn_delete_section.setObjectName("dangerButton")
        self.btn_delete_section.clicked.connect(self.delete_section)
        self.btn_delete_item = QPushButton("Excluir item")
        self.btn_delete_item.setObjectName("dangerButton")
        self.btn_delete_item.clicked.connect(self.delete_item)
        self.btn_expand_all = QPushButton("Expandir")
        self.btn_expand_all.clicked.connect(self.expand_all_sections)
        self.btn_collapse_all = QPushButton("Recolher")
        self.btn_collapse_all.clicked.connect(self.collapse_all_sections)
        self.btn_export_pdf = QPushButton("PDF")
        self.btn_export_pdf.clicked.connect(self.export_pdf)

        self.btn_sheet_scanner_tools = QPushButton("Scanner ▾")
        sheet_scanner_menu = QMenu(self.btn_sheet_scanner_tools)
        review_action = QAction("Revisar itens detectados…", self)
        review_action.triggered.connect(self.review_active_scan)
        diagnostics_action = QAction("Executar diagnóstico", self)
        diagnostics_action.triggered.connect(self.show_scan_diagnostics)
        report_action = QAction("Relatório técnico", self)
        report_action.triggered.connect(self.show_scan_report)
        sheet_scanner_menu.addAction(review_action)
        sheet_scanner_menu.addSeparator()
        sheet_scanner_menu.addAction(diagnostics_action)
        sheet_scanner_menu.addAction(report_action)
        self.btn_sheet_scanner_tools.setMenu(sheet_scanner_menu)

        buttons = [
            self.btn_expand_all, self.btn_collapse_all, self.btn_add_section,
            self.btn_rename_section, self.btn_add_item, self.btn_delete_section,
            self.btn_delete_item, self.btn_sheet_scanner_tools, self.btn_export_pdf,
        ]
        for index, button in enumerate(buttons):
            tools.addWidget(button, index // 5, index % 5)
        for column in range(5):
            tools.setColumnStretch(column, 1)
        layout.addWidget(tools_panel)

        self.checklist_table = QTableWidget()
        self.checklist_table.setObjectName("checklistSheetTable")
        self.checklist_table.setColumnCount(len(CHECKLIST_COLUMNS))
        self.checklist_table.setHorizontalHeaderLabels(CHECKLIST_COLUMNS)
        self.checklist_table.verticalHeader().setVisible(False)
        self.checklist_table.setAlternatingRowColors(False)
        self.checklist_table.setWordWrap(True)
        self.checklist_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.checklist_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.checklist_table.setMinimumHeight(360)
        self.checklist_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.checklist_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.checklist_table.verticalScrollBar().setSingleStep(14)
        self.checklist_table.verticalScrollBar().setPageStep(260)
        self.checklist_table.horizontalScrollBar().setSingleStep(18)

        self.checklist_table.itemChanged.connect(self.on_checklist_table_item_changed)
        self.checklist_table.itemSelectionChanged.connect(self.on_checklist_table_selection_changed)
        self.checklist_table.cellClicked.connect(self.on_checklist_table_cell_clicked)

        header = self.checklist_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.checklist_table.setColumnWidth(0, 58)
        self.checklist_table.setColumnWidth(3, 110)
        self.checklist_table.setColumnWidth(4, 68)

        layout.addWidget(self.checklist_table, 1)
        return panel

    def create_selected_item_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("guidancePanel")
        panel.setMinimumWidth(320)
        panel.setMaximumWidth(430)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("Documentos necessários")
        title.setObjectName("sectionTitle")
        self.item_badge = QLabel("Nenhum item")
        self.item_badge.setObjectName("statusBadge")
        title_row.addWidget(title, 1)
        title_row.addWidget(self.item_badge)
        layout.addLayout(title_row)

        self.scan_info_label = QLabel(
            "Selecione um item na folha para visualizar e editar as orientações."
        )
        self.scan_info_label.setObjectName("mutedText")
        self.scan_info_label.setWordWrap(True)
        layout.addWidget(self.scan_info_label)

        description_label = QLabel("Descrição")
        description_label.setProperty("inspectorLabel", True)
        self.description_input = QPlainTextEdit()
        self.description_input.setPlaceholderText("Descrição complementar do item")
        self.configure_text_editor(self.description_input, 90)
        layout.addWidget(description_label)
        layout.addWidget(self.description_input)

        docs_label = QLabel("Documentos mínimos")
        docs_label.setProperty("inspectorLabel", True)
        self.required_documents_input = QPlainTextEdit()
        self.required_documents_input.setPlaceholderText("Um documento mínimo por linha")
        self.required_documents_input.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.required_documents_input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.required_documents_input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.required_documents_input.verticalScrollBar().setSingleStep(12)
        self.required_documents_input.setMinimumHeight(150)
        self.required_documents_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(docs_label)
        layout.addWidget(self.required_documents_input, 1)

        notes_label = QLabel("Observações de conferência")
        notes_label.setProperty("inspectorLabel", True)
        self.notes_input = QPlainTextEdit()
        self.notes_input.setPlaceholderText("Uma observação de conferência por linha")
        self.notes_input.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.notes_input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.notes_input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.notes_input.verticalScrollBar().setSingleStep(12)
        self.notes_input.setMinimumHeight(120)
        self.notes_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(notes_label)
        layout.addWidget(self.notes_input, 1)

        self.btn_save_item = QPushButton("Salvar orientações")
        self.btn_save_item.setObjectName("primaryButton")
        self.btn_save_item.clicked.connect(self.save_item)
        layout.addWidget(self.btn_save_item)
        return panel

    # ------------------------------------------------------------ scanner page
    def create_scanner_page(self) -> QWidget:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.configure_scroll_area(scroll)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 26)
        layout.setSpacing(18)

        hero = QFrame()
        hero.setObjectName("scannerHero")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(24, 22, 24, 22)
        hero_layout.setSpacing(10)

        title = QLabel("Scanner de checklist")
        title.setObjectName("pageTitle")
        subtitle = QLabel(
            "Um único fluxo localiza a estrutura, confere a grade do PDF, associa as colunas, "
            "mede a confiança e só então apresenta os itens para revisão."
        )
        subtitle.setObjectName("mutedText")
        subtitle.setWordWrap(True)

        actions = QHBoxLayout()
        self.btn_scan_page = QPushButton("Analisar documento")
        self.btn_scan_page.setObjectName("primaryButton")
        self.btn_scan_page.clicked.connect(self.scan_file)
        actions.addWidget(self.btn_scan_page)

        self.btn_scanner_tools = QPushButton("Ferramentas do scanner")
        scanner_menu = QMenu(self.btn_scanner_tools)
        self.action_review_scan = QAction("Revisar itens encontrados…", self)
        self.action_review_scan.triggered.connect(self.review_last_scan)
        self.action_diagnostics_scan = QAction("Executar diagnóstico", self)
        self.action_diagnostics_scan.triggered.connect(self.show_scan_diagnostics)
        self.action_report_scan = QAction("Relatório técnico", self)
        self.action_report_scan.triggered.connect(self.show_scan_report)
        scanner_menu.addAction(self.action_review_scan)
        scanner_menu.addSeparator()
        scanner_menu.addAction(self.action_diagnostics_scan)
        scanner_menu.addAction(self.action_report_scan)
        self.btn_scanner_tools.setMenu(scanner_menu)
        actions.addWidget(self.btn_scanner_tools)
        actions.addStretch()

        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 6)
        self.scan_progress.setValue(0)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.hide()

        self.scan_stage_label = QLabel("Selecione um PDF, DOCX ou DOCM para começar.")
        self.scan_stage_label.setObjectName("mutedText")

        hero_layout.addWidget(title)
        hero_layout.addWidget(subtitle)
        hero_layout.addLayout(actions)
        hero_layout.addWidget(self.scan_progress)
        hero_layout.addWidget(self.scan_stage_label)
        layout.addWidget(hero)

        explanation = QFrame()
        explanation.setObjectName("panelCard")
        explanation_layout = QVBoxLayout(explanation)
        explanation_layout.setContentsMargins(18, 16, 18, 16)
        explanation_layout.setSpacing(8)

        explanation_title = QLabel("Etapas da análise")
        explanation_title.setObjectName("sectionTitle")
        explanation_text = QLabel(
            "1. Verifica o arquivo e a quantidade de páginas.\n"
            "2. Extrai a estrutura física do documento.\n"
            "3. Nos PDFs oficiais, usa a grade como autoridade para separar Documento, Normativo, S/N/NA, Folha e Observação.\n"
            "4. Calcula evidências e confiança por item.\n"
            "5. Executa verificações estruturais: duplicidades, numeração, seções e página de origem.\n"
            "6. Mostra todos os itens para revisão antes de criar o checklist."
        )
        explanation_text.setObjectName("mutedText")
        explanation_text.setWordWrap(True)

        self.scanner_result_label = QLabel("Nenhum documento analisado nesta sessão.")
        self.scanner_result_label.setObjectName("statusBadge")
        self.scanner_result_label.setWordWrap(True)

        explanation_layout.addWidget(explanation_title)
        explanation_layout.addWidget(explanation_text)
        explanation_layout.addWidget(self.scanner_result_label)
        layout.addWidget(explanation)
        layout.addStretch()

        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        return page

    # ------------------------------------------------------------- refresh UI
    def refresh_all(self) -> None:
        self.refresh_home_metrics()
        self.refresh_checklist_list()
        self.sync_active_checklist_list_item()
        self.refresh_checklist_sheet()
        self.populate_item_editor()

    def refresh_home_metrics(self) -> None:
        total_sections = sum(len(template.get("sections", [])) for template in self.templates)
        total_items = sum(
            len(section.get("items", []))
            for template in self.templates
            for section in template.get("sections", [])
        )
        active_template = self.get_active_template()

        self.metric_checklists.value_label.setText(str(len(self.templates)))  # type: ignore[attr-defined]
        self.metric_sections.value_label.setText(str(total_sections))  # type: ignore[attr-defined]
        self.metric_items.value_label.setText(str(total_items))  # type: ignore[attr-defined]
        self.metric_active.value_label.setText(active_template.get("title", "Nenhum") if active_template else "Nenhum")  # type: ignore[attr-defined]

    def refresh_checklist_list(self) -> None:
        if not hasattr(self, "checklist_list"):
            return

        search = normalize_text(self.search_input.text())
        selected_row = -1

        self.checklist_list.blockSignals(True)
        self.checklist_list.clear()

        for template in self.templates:
            searchable = normalize_text(
                " ".join(
                    [
                        str(template.get("title") or ""),
                        str(template.get("subtitle") or ""),
                        str(template.get("baseLegal") or ""),
                    ]
                )
            )

            if search and search not in searchable:
                continue

            sections = template.get("sections") if isinstance(template.get("sections"), list) else []
            item_count = sum(len(section.get("items", [])) for section in sections if isinstance(section, dict))
            title = str(template.get("title") or "Checklist sem nome")
            subtitle = str(template.get("subtitle") or "Sem subtítulo")

            item = QListWidgetItem(f"{title}\n{subtitle} · {len(sections)} seção(ões), {item_count} item(ns)")
            item.setData(Qt.ItemDataRole.UserRole, str(template.get("id")))
            item.setSizeHint(item.sizeHint().expandedTo(item.sizeHint()))
            self.checklist_list.addItem(item)

            if str(template.get("id")) == self.active_checklist_id:
                selected_row = self.checklist_list.count() - 1

        if selected_row >= 0:
            self.checklist_list.setCurrentRow(selected_row)
            current_item = self.checklist_list.item(selected_row)
            if current_item is not None:
                self.checklist_list.scrollToItem(current_item, QAbstractItemView.ScrollHint.PositionAtCenter)
        else:
            self.checklist_list.setCurrentItem(None)

        self.checklist_list.blockSignals(False)

    def refresh_checklist_sheet(self) -> None:
        if not hasattr(self, "checklist_table"):
            return

        template = self.get_active_template()
        search_text = normalize_text(self.sheet_search_input.text()) if hasattr(self, "sheet_search_input") else ""
        vertical_scroll = self.checklist_table.verticalScrollBar().value()
        horizontal_scroll = self.checklist_table.horizontalScrollBar().value()

        self.loading_table = True
        self.checklist_table.blockSignals(True)
        self.checklist_table.clearSpans()
        self.checklist_table.setRowCount(0)
        self.checklist_row_map = []

        sections = template.get("sections", []) if template else []
        total_items = sum(len(section.get("items", [])) for section in sections if isinstance(section, dict))

        if template:
            self.sheet_subtitle.setText(format_subtitle(template))
            self.sheet_counts.setText(f"{len(sections)} seção(ões) · {total_items} item(ns)")
        else:
            self.sheet_subtitle.setText("Nenhum checklist selecionado")
            self.sheet_counts.setText("0 seção(ões) · 0 item(ns)")

        selected_row = -1
        search_active = bool(search_text)

        for section_index, section in enumerate(sections):
            if not isinstance(section, dict):
                continue

            section_key = self.get_section_key(section, section_index)
            section_searchable = normalize_text(f"{section.get('number', '')} {section.get('title', '')}")
            items = section.get("items") if isinstance(section.get("items"), list) else []
            visible_items: list[tuple[int, dict[str, Any]]] = []

            for item_index, item_data in enumerate(items):
                if not isinstance(item_data, dict):
                    continue

                if search_text and search_text not in normalize_text(item_search_text(item_data)) and search_text not in section_searchable:
                    continue

                visible_items.append((item_index, item_data))

            if search_text and not visible_items and search_text not in section_searchable:
                continue

            expanded = search_active or section_key in self.expanded_section_ids
            section_row = self.checklist_table.rowCount()
            self.checklist_table.insertRow(section_row)
            self.checklist_table.setSpan(section_row, 0, 1, len(CHECKLIST_COLUMNS))
            self.checklist_row_map.append({"type": "section", "section_index": section_index, "item_index": -1})

            arrow = "▼" if expanded else "▶"
            item_label = "item" if len(items) == 1 else "itens"
            section_text = f"{arrow}  {section.get('number', '')}. {section.get('title', '')}    ·    {len(items)} {item_label}".strip()
            section_item = make_sheet_item(
                section_text,
                editable=False,
                bold=True,
                background=self.section_row_color(),
            )
            section_item.setToolTip(
                "Clique uma vez para expandir ou recolher a seção. "
                "Use Renomear seção para alterar o nome."
            )
            self.checklist_table.setItem(section_row, 0, section_item)
            self.checklist_table.setRowHeight(section_row, 34)

            if self.active_section_index == section_index and (self.active_item_index == -1 or not expanded):
                selected_row = section_row

            if not expanded:
                continue

            for item_index, item_data in visible_items:
                row = self.checklist_table.rowCount()
                self.checklist_table.insertRow(row)
                self.checklist_row_map.append({"type": "item", "section_index": section_index, "item_index": item_index})

                has_extra_guidance = item_has_extra_guidance(item_data)
                pin_marker = "📌 " if has_extra_guidance else ""
                values = [
                    f"{pin_marker}{item_data.get('number') or ''}".strip(),
                    item_data.get("documento"),
                    item_data.get("normativo"),
                    item_data.get("situacao") or "N/A",
                    item_data.get("folha"),
                    item_data.get("observacao"),
                ]

                guidance_tooltip = (
                    "Este item possui informações extras no painel inferior "
                    "(descrição, documentos mínimos ou observações)."
                    if has_extra_guidance
                    else ""
                )

                for column, value in enumerate(values):
                    align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    if column in {0, 3, 4}:
                        align = Qt.AlignmentFlag.AlignCenter

                    cell = make_sheet_item(value, editable=(column != 3), alignment=align)
                    if guidance_tooltip:
                        cell.setToolTip(guidance_tooltip)
                    self.checklist_table.setItem(row, column, cell)

                status_combo = QComboBox()
                status_combo.setObjectName("checklistStatusCombo")
                status_combo.addItems(["Escolher", "Sim", "Não", "Não Aplicável"])
                current_status = str(item_data.get("situacao") or "").strip()
                status_combo.setCurrentText(current_status if current_status in {"Sim", "Não", "Não Aplicável"} else "Escolher")
                status_combo.currentTextChanged.connect(
                    lambda value, s=section_index, i=item_index: self.on_status_combo_changed(s, i, value)
                )
                self.checklist_table.setCellWidget(row, 3, status_combo)

                if self.active_section_index == section_index and self.active_item_index == item_index:
                    selected_row = row

        self.checklist_table.resizeRowsToContents()

        if selected_row >= 0:
            self.checklist_table.selectRow(selected_row)

        self.checklist_table.blockSignals(False)
        self.loading_table = False

        # Rebuilding a QTableWidget resets the viewport to the beginning. Keep
        # the user's reading position stable when a section is expanded,
        # collapsed or refreshed after an edit. Restore once immediately and
        # once after Qt finishes the pending layout pass.
        self._restore_checklist_scroll(vertical_scroll, horizontal_scroll)
        QTimer.singleShot(0, lambda v=vertical_scroll, h=horizontal_scroll: self._restore_checklist_scroll(v, h))

    def _restore_checklist_scroll(self, vertical: int, horizontal: int) -> None:
        if not hasattr(self, "checklist_table"):
            return
        vertical_bar = self.checklist_table.verticalScrollBar()
        horizontal_bar = self.checklist_table.horizontalScrollBar()
        vertical_bar.setValue(max(vertical_bar.minimum(), min(vertical, vertical_bar.maximum())))
        horizontal_bar.setValue(max(horizontal_bar.minimum(), min(horizontal, horizontal_bar.maximum())))

    def get_section_key(self, section: dict[str, Any], section_index: int) -> str:
        section_id = str(section.get("id") or "").strip()
        return section_id or f"section-index-{section_index}"

    def on_checklist_table_cell_clicked(self, row: int, _column: int) -> None:
        if self.loading_table or row < 0 or row >= len(self.checklist_row_map):
            return

        row_info = self.checklist_row_map[row]

        if row_info.get("type") != "section":
            return

        section_index = int(row_info.get("section_index", -1))
        template = self.get_active_template()

        if not template:
            return

        sections = template.get("sections") if isinstance(template.get("sections"), list) else []

        if section_index < 0 or section_index >= len(sections):
            return

        self.active_section_index = section_index
        self.active_item_index = -1
        self.pending_delete_key = None

        # Search results stay expanded so matching items remain visible.
        if normalize_text(self.sheet_search_input.text()):
            self.populate_item_editor()
            return

        section_key = self.get_section_key(sections[section_index], section_index)

        if section_key in self.expanded_section_ids:
            self.expanded_section_ids.remove(section_key)
        else:
            self.expanded_section_ids.add(section_key)

        self.refresh_checklist_sheet()
        self.populate_item_editor()

    def expand_all_sections(self) -> None:
        template = self.get_active_template()

        if not template:
            return

        sections = template.get("sections") if isinstance(template.get("sections"), list) else []
        self.expanded_section_ids = {
            self.get_section_key(section, index)
            for index, section in enumerate(sections)
            if isinstance(section, dict)
        }
        self.refresh_checklist_sheet()
        self.show_status("Todas as seções foram expandidas.")

    def collapse_all_sections(self) -> None:
        self.expanded_section_ids.clear()
        self.active_item_index = -1
        self.refresh_checklist_sheet()
        self.populate_item_editor()
        self.show_status("Todas as seções foram recolhidas.")

    def show_empty_state(self) -> None:
        self.active_checklist_id = None
        self.checklist_title_display.setText("Nenhum checklist")
        self.checklist_subtitle_display.setText("Use Abrir scanner ou Novo vazio para começar.")
        self.sheet_subtitle.setText("Nenhum checklist selecionado")
        self.active_badge.setText("Nenhum ativo")
        self.clear_metadata_inputs()
        self.refresh_checklist_sheet()
        self.populate_item_editor()
        self.expanded_section_ids.clear()
        self.navigate_to(HOME_PAGE)

    # --------------------------------------------------------------- selection
    def on_checklist_selection_changed(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        if current is None:
            return

        checklist_id = current.data(Qt.ItemDataRole.UserRole)

        if checklist_id:
            self.select_checklist(str(checklist_id))

    def sync_active_checklist_list_item(self) -> None:
        if not hasattr(self, "checklist_list") or not self.active_checklist_id:
            return
        self.checklist_list.blockSignals(True)
        try:
            for row in range(self.checklist_list.count()):
                item = self.checklist_list.item(row)
                if item is not None and str(item.data(Qt.ItemDataRole.UserRole)) == self.active_checklist_id:
                    self.checklist_list.setCurrentRow(row)
                    self.checklist_list.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter)
                    break
        finally:
            self.checklist_list.blockSignals(False)

    def select_checklist(self, checklist_id: str) -> None:
        template = self.get_template(checklist_id)

        if not template:
            return

        self.active_checklist_id = checklist_id
        self.active_section_index = 0
        self.active_item_index = -1
        self.pending_delete_key = None
        # Every checklist starts fully collapsed. Sections are expanded only
        # when the user opens one, uses Expandir, or a search needs to reveal
        # matching rows.
        self.expanded_section_ids.clear()

        self.populate_metadata_inputs(template)
        self.refresh_home_metrics()
        self.refresh_checklist_list()
        self.sync_active_checklist_list_item()
        self.refresh_checklist_sheet()
        self.populate_item_editor()
        self.navigate_to(CHECKLIST_PAGE)
        self.show_status(f"Checklist ativo: {template.get('title')}")

    def on_checklist_table_selection_changed(self) -> None:
        if self.loading_table:
            return

        selected_rows = self.checklist_table.selectionModel().selectedRows()

        if not selected_rows:
            return

        row = selected_rows[0].row()

        if row < 0 or row >= len(self.checklist_row_map):
            return

        row_info = self.checklist_row_map[row]
        self.active_section_index = int(row_info.get("section_index", 0))
        self.active_item_index = int(row_info.get("item_index", -1))
        self.pending_delete_key = None
        self.populate_item_editor()

    def on_status_combo_changed(self, section_index: int, item_index: int, value: str) -> None:
        if self.loading_table:
            return
        vertical_scroll = self.checklist_table.verticalScrollBar().value() if hasattr(self, "checklist_table") else 0
        horizontal_scroll = self.checklist_table.horizontalScrollBar().value() if hasattr(self, "checklist_table") else 0
        template = self.get_active_template()
        if not template:
            return
        sections = template.get("sections") if isinstance(template.get("sections"), list) else []
        if section_index < 0 or section_index >= len(sections):
            return
        items = sections[section_index].get("items") if isinstance(sections[section_index].get("items"), list) else []
        if item_index < 0 or item_index >= len(items):
            return
        items[item_index]["situacao"] = "" if value == "Escolher" else value
        self.save_now(silent=True)
        self.populate_item_editor()
        self._restore_checklist_scroll(vertical_scroll, horizontal_scroll)
        QTimer.singleShot(0, lambda v=vertical_scroll, h=horizontal_scroll: self._restore_checklist_scroll(v, h))
        self.show_status("Situação atualizada.")

    def on_checklist_table_item_changed(self, table_item: QTableWidgetItem) -> None:
        if self.loading_table:
            return

        row = table_item.row()
        column = table_item.column()

        if row < 0 or row >= len(self.checklist_row_map):
            return

        row_info = self.checklist_row_map[row]
        template = self.get_active_template()

        if not template:
            return

        sections = template.get("sections") if isinstance(template.get("sections"), list) else []
        section_index = int(row_info.get("section_index", -1))

        if section_index < 0 or section_index >= len(sections):
            return

        if row_info.get("type") == "section":
            # Section bars are renamed through the explicit Renomear seção
            # action. Keeping the bar itself read-only avoids a click used to
            # expand/collapse from destroying an in-progress inline editor.
            return

        if row_info.get("type") != "item":
            return

        item_index = int(row_info.get("item_index", -1))
        items = sections[section_index].get("items") if isinstance(sections[section_index].get("items"), list) else []

        if item_index < 0 or item_index >= len(items):
            return

        field_name = ITEM_FIELD_BY_COLUMN.get(column)

        if not field_name:
            return

        value = table_item.text().strip()

        if column == 0 and value.startswith("📌"):
            value = value.removeprefix("📌").strip()
            self.loading_table = True
            table_item.setText(value)
            self.loading_table = False

        items[item_index][field_name] = value
        self.save_now(silent=True)
        self.refresh_home_metrics()
        self.refresh_checklist_list()
        self.populate_item_editor()
        self.show_status("Linha atualizada.")

    # -------------------------------------------------------------- populate
    def populate_metadata_inputs(self, template: dict[str, Any]) -> None:
        self.loading_controls = True
        self.checklist_title_display.setText(str(template.get("title") or "Checklist"))
        self.checklist_subtitle_display.setText(format_subtitle(template))
        self.active_badge.setText("Checklist ativo")
        self.title_input.setText(str(template.get("title") or ""))
        self.subtitle_input.setText(str(template.get("subtitle") or ""))
        self.base_legal_input.setText(str(template.get("baseLegal") or ""))
        self.loading_controls = False

    def clear_metadata_inputs(self) -> None:
        self.loading_controls = True
        self.title_input.clear()
        self.subtitle_input.clear()
        self.base_legal_input.clear()
        self.loading_controls = False

    def populate_item_editor(self) -> None:
        if not hasattr(self, "description_input"):
            return

        item_data = self.get_active_item()
        self.loading_controls = True

        enabled = item_data is not None
        widgets = [self.description_input, self.required_documents_input, self.notes_input]

        for widget in widgets:
            widget.setEnabled(enabled)

        self.btn_save_item.setEnabled(enabled)
        self.btn_delete_item.setEnabled(self.get_active_section() is not None)
        self.btn_delete_section.setEnabled(self.get_active_section() is not None)
        self.btn_rename_section.setEnabled(self.get_active_section() is not None)

        if not item_data:
            section = self.get_active_section()

            if section:
                self.item_badge.setText(f"Seção {section.get('number', '')}")
                self.scan_info_label.setText(
                    "Seção selecionada. Clique na barra da seção para expandir/recolher, "
                    "use Renomear seção para alterar o nome ou Adicionar item para incluir uma linha."
                )
            else:
                self.item_badge.setText("Nenhum item")
                self.scan_info_label.setText("Selecione ou adicione um item para revisar as orientações.")

            self.description_input.clear()
            self.required_documents_input.clear()
            self.notes_input.clear()
        else:
            marker = " 📌" if item_has_extra_guidance(item_data) else ""
            self.item_badge.setText(f"Item {item_data.get('number', '')}{marker}")
            self.scan_info_label.setText(self.format_scan_info(item_data))
            self.description_input.setPlainText(str(item_data.get("description") or ""))
            self.required_documents_input.setPlainText("\n".join(normalize_text_list(item_data.get("requiredDocuments"))))
            self.notes_input.setPlainText("\n".join(normalize_text_list(item_data.get("notes"))))

        self.loading_controls = False

    def format_scan_info(self, item_data: dict[str, Any]) -> str:
        confidence = str(item_data.get("scanConfidence") or "manual").strip()
        evidence = normalize_text_list(item_data.get("scanEvidence"))
        page = int(item_data.get("scanPage") or 0)
        source = str(item_data.get("scanSource") or "").strip()

        if evidence:
            where = f"Página {page}. " if page else ""
            technical = f" Origem técnica: {source}." if source else ""
            return f"{where}Status do scanner: {confidence}. {'; '.join(evidence)}{technical}"

        return "Item manual ou já revisado. Edite a linha na folha e as orientações abaixo."

    # --------------------------------------------------------------- actions
    def scan_file(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Analisar documento",
            "",
            "Documentos (*.pdf *.docx *.docm)",
        )

        if not file_path:
            self.show_status("Scanner cancelado.")
            return

        self.scan_progress.show()
        self.scan_progress.setValue(0)
        self.btn_scan_page.setEnabled(False)

        def update_progress(current: int, total: int, message: str) -> None:
            self.scan_progress.setRange(0, total)
            self.scan_progress.setValue(current)
            self.scan_stage_label.setText(message)
            QApplication.processEvents()

        try:
            result = analyze_document(file_path, progress=update_progress)
            self.last_scan_result = result
            report = result.report.as_dict()
            self.scanner_result_label.setText(
                f"{Path(file_path).name}: {report.get('candidate_count', 0)} item(ns), "
                f"{len(report.get('sections', []))} seção(ões), {report.get('page_count', 0)} página(s)."
            )

            if result.report.blocking_issue_count:
                self.show_status("A análise encontrou problemas bloqueantes. Abra o diagnóstico.")
                ScanDiagnosticsDialog(report, self).exec()
                return

            dialog = ScanReviewDialog(result.candidate_list(), self, report=report)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                self.show_status("Análise concluída. A importação foi cancelada; o relatório permanece disponível.")
                return

            reviewed = dialog.reviewed_candidates()
            template = build_template_from_scan(result, reviewed)
            template["title"] = self.create_unique_title(str(template.get("title") or Path(file_path).stem))

            self.templates.append(template)
            save_templates(self.templates)
            self.select_checklist(str(template["id"]))
            self.refresh_all()

            sections = template.get("sections", [])
            item_count = sum(len(section.get("items", [])) for section in sections)
            message = (
                f"Checklist criado: {template['title']} · {len(sections)} seção(ões), "
                f"{item_count} item(ns). Revise a folha antes de usar como definitivo."
            )
            self.scanner_result_label.setText(message)
            self.show_status(message)
        except Exception as error:
            self.scan_stage_label.setText("A análise não foi concluída.")
            self.show_status(f"Erro no scanner: {error}")
        finally:
            self.btn_scan_page.setEnabled(True)
            self.scan_progress.hide()

    def review_last_scan(self) -> None:
        if self.last_scan_result is None:
            self.review_active_scan()
            return
        dialog = ScanReviewDialog(
            self.last_scan_result.candidate_list(),
            self,
            report=self.last_scan_result.report.as_dict(),
        )
        dialog.exec()

    def review_active_scan(self) -> None:
        template = self.get_active_template()
        if not template:
            self.show_status("Selecione um checklist primeiro.")
            return
        candidates = template.get("scanCandidates") if isinstance(template.get("scanCandidates"), list) else []
        if not candidates:
            self.show_status("Este checklist não possui dados de scanner para revisar.")
            return
        report = template.get("scanReport") if isinstance(template.get("scanReport"), dict) else {}
        dialog = ScanReviewDialog([dict(item) for item in candidates if isinstance(item, dict)], self, report=report)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            template["scanCandidates"] = dialog.reviewed_candidates()
            self.save_now(silent=True)
            self.show_status("Revisão do scanner registrada. A folha existente não foi reescrita automaticamente.")

    def _current_scan_report(self) -> dict[str, Any] | None:
        if self.pages.currentIndex() == SCANNER_PAGE and self.last_scan_result is not None:
            return self.last_scan_result.report.as_dict()
        template = self.get_active_template()
        if template and isinstance(template.get("scanReport"), dict) and template.get("scanReport"):
            return dict(template.get("scanReport") or {})
        if self.last_scan_result is not None:
            return self.last_scan_result.report.as_dict()
        return None

    def show_scan_diagnostics(self) -> None:
        report = self._current_scan_report()
        if not report:
            self.show_status("Ainda não há um diagnóstico de scanner disponível.")
            return
        ScanDiagnosticsDialog(report, self).exec()

    def show_scan_report(self) -> None:
        report = self._current_scan_report()
        if not report:
            self.show_status("Ainda não há um relatório de scanner disponível.")
            return
        ScanReportDialog(report, self).exec()

    def create_empty_checklist(self) -> None:
        title = self.create_unique_title("Novo Checklist")

        template = {
            "id": new_id("checklist"),
            "title": title,
            "subtitle": "",
            "baseLegal": "",
            "description": "",
            "sections": [
                {
                    "id": new_id("section"),
                    "number": "1",
                    "title": "NOVA SEÇÃO",
                    "items": [],
                }
            ],
        }

        self.templates.append(template)
        self.save_now(silent=True)
        self.select_checklist(str(template["id"]))
        self.show_status("Checklist vazio criado.")

    def copy_active_checklist(self) -> None:
        template = self.get_active_template()

        if not template:
            self.show_status("Selecione um checklist para copiar.")
            return

        copied = copy.deepcopy(template)
        copied["id"] = new_id("checklist")
        copied["title"] = self.create_unique_title(f"{template.get('title', 'Checklist')} - Cópia")

        for section in copied.get("sections", []):
            section["id"] = new_id("section")

            for item_data in section.get("items", []):
                item_data["id"] = new_id("item")

        self.templates.append(copied)
        self.save_now(silent=True)
        self.select_checklist(str(copied["id"]))
        self.show_status(f"Checklist copiado: {copied['title']}")

    def delete_active_checklist(self) -> None:
        template = self.get_active_template()

        if not template:
            self.show_status("Nenhum checklist selecionado para excluir.")
            return

        key = f"checklist:{template.get('id')}"

        if self.pending_delete_key != key:
            self.pending_delete_key = key
            self.show_status("Clique novamente em Excluir checklist para confirmar.")
            return

        self.pending_delete_key = None
        self.templates = [item for item in self.templates if item.get("id") != template.get("id")]
        self.active_checklist_id = None
        self.active_section_index = 0
        self.active_item_index = -1
        self.save_now(silent=True)
        self.refresh_checklist_list()

        if self.templates:
            self.select_checklist(str(self.templates[0]["id"]))
        else:
            self.show_empty_state()

        self.show_status("Checklist excluído.")

    def save_metadata(self) -> None:
        template = self.get_active_template()

        if not template:
            self.show_status("Selecione um checklist primeiro.")
            return

        title = self.title_input.text().strip()

        if not title:
            self.show_status("O nome do checklist não pode ficar vazio.")
            return

        template["title"] = title
        template["subtitle"] = self.subtitle_input.text().strip()
        template["baseLegal"] = self.base_legal_input.text().strip()

        self.save_now(silent=True)
        self.populate_metadata_inputs(template)
        self.refresh_checklist_list()
        self.refresh_home_metrics()
        self.refresh_checklist_sheet()
        self.show_status("Dados do checklist salvos.")

    def add_section(self) -> None:
        template = self.get_active_template()

        if not template:
            self.create_empty_checklist()
            template = self.get_active_template()

        if not template:
            return

        sections = template.setdefault("sections", [])
        section_number = str(len(sections) + 1)
        sections.append(
            {
                "id": new_id("section"),
                "number": section_number,
                "title": "NOVA SEÇÃO",
                "items": [],
            }
        )

        self.active_section_index = len(sections) - 1
        self.active_item_index = -1
        self.save_now(silent=True)
        self.refresh_all()
        self.show_status("Seção adicionada. Ela começa recolhida; clique na barra para expandir.")

    def rename_section(self) -> None:
        section = self.get_active_section()

        if not section:
            self.show_status("Selecione uma seção para renomear.")
            return

        current_title = str(section.get("title") or "").strip()
        new_title, accepted = QInputDialog.getText(
            self,
            "Renomear seção",
            f"Novo nome da seção {section.get('number', '')}:",
            text=current_title,
        )

        if not accepted:
            return

        new_title = new_title.strip()

        if not new_title:
            self.show_status("O nome da seção não pode ficar vazio.")
            return

        section["title"] = new_title
        self.save_now(silent=True)
        self.refresh_home_metrics()
        self.refresh_checklist_list()
        self.sync_active_checklist_list_item()
        self.refresh_checklist_sheet()
        self.populate_item_editor()
        self.show_status(f"Seção {section.get('number', '')} renomeada para: {new_title}")

    def delete_section(self) -> None:
        template = self.get_active_template()
        section = self.get_active_section()

        if not template or not section:
            self.show_status("Selecione uma seção para excluir.")
            return

        key = f"section:{self.active_section_index}"

        if self.pending_delete_key != key:
            self.pending_delete_key = key
            self.show_status("Clique novamente em Excluir seção para confirmar. Os itens da seção também serão excluídos.")
            return

        self.pending_delete_key = None
        sections = template.get("sections", [])
        del sections[self.active_section_index]
        self.active_section_index = max(0, self.active_section_index - 1)
        self.active_item_index = -1
        self.save_now(silent=True)
        self.refresh_all()
        self.show_status("Seção excluída.")

    def add_item(self) -> None:
        section = self.get_active_section()

        if not section:
            self.add_section()
            section = self.get_active_section()

        if not section:
            return

        items = section.setdefault("items", [])
        item_number = f"{section.get('number')}.{len(items) + 1}"
        items.append(
            {
                "id": new_id("item"),
                "number": item_number,
                "documento": "Novo documento / informação",
                "normativo": "",
                "situacao": "",
                "folha": "",
                "observacao": "",
                "description": "",
                "requiredDocuments": [],
                "notes": [],
            }
        )

        self.active_item_index = len(items) - 1
        self.expanded_section_ids.add(self.get_section_key(section, self.active_section_index))
        self.save_now(silent=True)
        self.refresh_all()
        self.show_status("Item adicionado. Edite a linha diretamente na folha.")

    def save_item(self) -> None:
        item_data = self.get_active_item()

        if not item_data:
            self.show_status("Selecione um item primeiro.")
            return

        item_data["description"] = self.description_input.toPlainText().strip()
        item_data["requiredDocuments"] = parse_lines(self.required_documents_input.toPlainText())
        item_data["notes"] = parse_lines(self.notes_input.toPlainText())

        if item_data.get("scanConfidence"):
            existing_evidence = normalize_text_list(item_data.get("scanEvidence"))
            if "Item revisado manualmente no editor." not in existing_evidence:
                existing_evidence.append("Item revisado manualmente no editor.")
            item_data["scanEvidence"] = existing_evidence
            item_data["scanConfidence"] = "reviewed"

        self.save_now(silent=True)
        self.refresh_checklist_sheet()
        self.populate_item_editor()
        self.show_status("Orientações do item salvas.")

    def delete_item(self) -> None:
        section = self.get_active_section()
        item_data = self.get_active_item()

        if not section or not item_data:
            self.show_status("Selecione um item para excluir.")
            return

        key = f"item:{self.active_section_index}:{self.active_item_index}"

        if self.pending_delete_key != key:
            self.pending_delete_key = key
            self.show_status("Clique novamente em Excluir item para confirmar.")
            return

        self.pending_delete_key = None
        items = section.get("items", [])
        del items[self.active_item_index]
        self.active_item_index = max(-1, self.active_item_index - 1)
        self.save_now(silent=True)
        self.refresh_all()
        self.show_status("Item excluído.")

    def export_active_checklist_json(self) -> None:
        template = self.get_active_template()
        if not template:
            self.show_status("Selecione um checklist para exportar em JSON.")
            return

        suggested_name = sanitize_filename(str(template.get("title") or "checklist")) + ".json"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar checklist JSON",
            suggested_name,
            "Checklist JSON (*.json)",
        )
        if not file_path:
            self.show_status("Exportação JSON cancelada.")
            return

        try:
            output_path = export_checklist_json(template, file_path)
            self.show_status(f"Checklist JSON exportado: {output_path}")
        except Exception as error:
            self.show_status(f"Erro ao exportar JSON: {error}")

    def import_checklist_json(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Importar checklist JSON",
            "",
            "Checklist JSON (*.json);;Todos os arquivos (*)",
        )
        if not file_path:
            self.show_status("Importação JSON cancelada.")
            return

        try:
            existing_ids = {str(template.get("id") or "") for template in self.templates}
            imported = import_checklists_json(file_path, existing_ids=existing_ids)
            if not imported:
                self.show_status("Nenhum checklist válido encontrado no JSON.")
                return
            self.templates.extend(imported)
            self.save_now(silent=True)
            self.refresh_all()
            self.select_checklist(str(imported[0]["id"]))
            count = len(imported)
            self.show_status(f"{count} checklist(s) importado(s) do JSON.")
        except Exception as error:
            self.show_status(f"Erro ao importar JSON: {error}")

    def export_pdf(self) -> None:
        template = self.get_active_template()

        if not template:
            self.show_status("Selecione um checklist para exportar.")
            return

        suggested_name = sanitize_filename(str(template.get("title") or "checklist")) + ".pdf"

        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Exportar PDF completo",
            suggested_name,
            "PDF (*.pdf)",
        )

        if not file_path:
            self.show_status("Exportação PDF cancelada.")
            return

        try:
            output_path = export_checklist_pdf(template, file_path)
            self.show_status(f"PDF exportado: {output_path}")
        except Exception as error:
            self.show_status(f"Erro ao exportar PDF: {error}")

    def save_now(self, silent: bool = False) -> None:
        try:
            path = save_templates(self.templates)

            if not silent:
                self.show_status(f"Dados salvos em: {path}")
        except Exception as error:
            self.show_status(f"Erro ao salvar: {error}")

    # ------------------------------------------------------------- data access
    def get_template(self, checklist_id: str) -> dict[str, Any] | None:
        for template in self.templates:
            if str(template.get("id")) == checklist_id:
                return template

        return None

    def get_active_template(self) -> dict[str, Any] | None:
        if not self.active_checklist_id:
            return None

        return self.get_template(self.active_checklist_id)

    def get_active_section(self) -> dict[str, Any] | None:
        template = self.get_active_template()

        if not template:
            return None

        sections = template.get("sections") if isinstance(template.get("sections"), list) else []

        if self.active_section_index < 0 or self.active_section_index >= len(sections):
            return None

        return sections[self.active_section_index]

    def get_active_item(self) -> dict[str, Any] | None:
        section = self.get_active_section()

        if not section:
            return None

        items = section.get("items") if isinstance(section.get("items"), list) else []

        if self.active_item_index < 0 or self.active_item_index >= len(items):
            return None

        return items[self.active_item_index]

    def create_unique_title(self, desired_title: str) -> str:
        existing = {normalize_text(str(template.get("title") or "")) for template in self.templates}
        base = desired_title.strip() or "Checklist"

        if normalize_text(base) not in existing:
            return base

        counter = 2

        while normalize_text(f"{base} {counter}") in existing:
            counter += 1

        return f"{base} {counter}"

    def show_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.statusBar().showMessage(message, 10000)


def make_sheet_item(
    value: Any,
    editable: bool = True,
    bold: bool = False,
    background: str | None = None,
    alignment: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
) -> QTableWidgetItem:
    item = QTableWidgetItem(str(value or ""))
    item.setTextAlignment(alignment)

    if not editable:
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

    if bold:
        font = item.font()
        font.setBold(True)
        item.setFont(font)

    if background:
        item.setBackground(QColor(background))

    return item


def parse_section_label(value: str, current_section: dict[str, Any]) -> tuple[str, str]:
    text = str(value or "").strip()
    match = re.match(r"^(\d+(?:\.\d+)*)\.\s*(.+)$", text)

    if match:
        return match.group(1), match.group(2).strip() or str(current_section.get("title") or "SEÇÃO")

    return str(current_section.get("number") or "1"), text or str(current_section.get("title") or "SEÇÃO")


def format_subtitle(template: dict[str, Any]) -> str:
    parts = []

    if template.get("subtitle"):
        parts.append(str(template.get("subtitle")))

    if template.get("baseLegal"):
        parts.append(f"Base legal: {template.get('baseLegal')}")

    if not parts:
        parts.append("Sem subtítulo / base legal")

    return " | ".join(parts)


def first_line(value: Any, max_length: int = 70) -> str:
    text = str(value or "").strip().splitlines()[0] if str(value or "").strip() else "Sem texto"

    if len(text) <= max_length:
        return text

    return text[: max_length - 1].rstrip() + "…"


def item_search_text(item_data: dict[str, Any]) -> str:
    return " ".join(
        str(item_data.get(field) or "")
        for field in ["number", "documento", "normativo", "situacao", "folha", "observacao", "description"]
    )


def normalize_text(value: str) -> str:
    normalized = str(value or "").lower()
    normalized = normalized.replace("á", "a").replace("à", "a").replace("â", "a").replace("ã", "a")
    normalized = normalized.replace("é", "e").replace("ê", "e")
    normalized = normalized.replace("í", "i")
    normalized = normalized.replace("ó", "o").replace("ô", "o").replace("õ", "o")
    normalized = normalized.replace("ú", "u")
    normalized = normalized.replace("ç", "c")
    return re.sub(r"\s+", " ", normalized.strip())


def parse_lines(value: str) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def normalize_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [str(item).strip() for item in value if str(item).strip()]


def item_has_extra_guidance(item_data: dict[str, Any]) -> bool:
    if str(item_data.get("description") or "").strip():
        return True

    if normalize_text_list(item_data.get("requiredDocuments")):
        return True

    if normalize_text_list(item_data.get("notes")):
        return True

    return False


def sanitize_filename(value: str) -> str:
    safe = re.sub(r"[<>:\"/\\|?*\x00-\x1F]", " ", value)
    safe = re.sub(r"\s+", " ", safe).strip()

    return safe[:120] or "checklist"
