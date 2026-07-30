from __future__ import annotations

import re
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.backup_manager import (
    create_backup,
    create_scheduled_backup,
    inspect_backup,
    restore_backup,
)
from app.dialogs.backup_contents_dialog import BackupContentsDialog
from app.dialogs.global_search_dialog import GlobalSearchDialog
from app.dialogs.profile_manager_dialog import ProfileManagerDialog
from app.docx_engine import DocumentGenerationError, generate_docx
from app.favorite_store import FavoriteStore
from app.field_utils import condition_matches, validate_field
from app.local_data import LocalDataStore
from app.pdf_converter import PdfConversionError, available_converter, convert_docx_to_pdf
from app.runtime_settings import (
    APPLICATION,
    ORGANIZATION,
    PORTABLE_MARKER,
    set_portable_mode,
)
from app.template_loader import TemplatePackage, discover_templates
from app.template_manager.template_manager_dialog import TemplateManagerDialog
from app.template_repository import TemplateRepository
from app.theme_manager import ThemeManager
from app.widgets.document_form import DocumentForm
from app.widgets.file_converter_page import FileConverterPage
from app.widgets.home_page import HomePage
from app.widgets.context_help import HelpIconButton, HelpLabel
from app.widgets.empty_state import EmptyState
from app.widgets.toast import show_toast
from app.widgets.sidebar import Sidebar
from app.widgets.template_header import TemplateHeader
from app.widgets.tutorial_page import TutorialPage


class MainWindow(QMainWindow):
    def __init__(self, project_root: Path, theme_manager: ThemeManager) -> None:
        super().__init__()
        self.project_root = Path(project_root)
        self.theme_manager = theme_manager
        self.templates_dir = self.project_root / "templates"
        self.data_dir = self.project_root / "data"
        self.default_output_dir = self.project_root / "output"
        self.settings = QSettings(ORGANIZATION, APPLICATION)
        self.favorite_store = FavoriteStore(self.settings)
        self.local_store = LocalDataStore(self.data_dir)
        self.repository = TemplateRepository(self.templates_dir)
        self.templates: list[TemplatePackage] = []
        self._active_template_id: str | None = None
        self._active_profile_id: str | None = None
        self._active_profile_name = ""
        self._restoring_draft = False
        self._form_dirty = False
        self._draft_choice_pending = False
        self._pending_draft: dict[str, Any] | None = None
        self._validation_issues: list[dict[str, str]] = []
        self._validation_issue_index = 0
        self._loading_preferences = False

        self.autosave_timer = QTimer(self)
        self.autosave_timer.setSingleShot(True)
        self.autosave_timer.setInterval(900)
        self.autosave_timer.timeout.connect(self._save_current_draft)

        self.setWindowTitle('Padroniza — Suíte de Documentos')
        self.resize(1400, 860)
        self.setMinimumSize(1080, 700)

        self._create_menu_bar()
        self._create_interface()
        self._create_status_bar()
        self._load_preferences()
        self._load_templates()
        self._refresh_profiles()
        self._refresh_recent_page()
        self._refresh_archive_page()
        self._refresh_audit_page()
        self._refresh_home_page()
        QTimer.singleShot(
            1200,
            self._run_scheduled_backup_if_due,
        )

    # UI -----------------------------------------------------------------------
    def _create_menu_bar(self) -> None:
        file_menu = self.menuBar().addMenu('&Arquivo')
        tools_menu = self.menuBar().addMenu('&Ferramentas')
        view_menu = self.menuBar().addMenu('&Exibir')
        help_menu = self.menuBar().addMenu('A&juda')

        search_action = QAction('Pesquisa e comandos…', self)
        search_action.setShortcut("Ctrl+K")
        search_action.triggered.connect(self._show_global_search)
        tools_menu.addAction(search_action)
        tools_menu.addSeparator()

        new_action = QAction('Novo documento', self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self._clear_form)
        file_menu.addAction(new_action)

        output_action = QAction(
            'Abrir pasta de saída',
            self,
        )
        output_action.triggered.connect(
            self._open_output_folder
        )
        file_menu.addAction(output_action)

        file_menu.addSeparator()

        exit_action = QAction('Sair', self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        templates_submenu = tools_menu.addMenu(
            'Modelos'
        )

        manage_templates_action = QAction(
            'Gerenciar modelos',
            self,
        )
        manage_templates_action.triggered.connect(
            self._open_template_manager
        )
        templates_submenu.addAction(
            manage_templates_action
        )

        refresh_templates_action = QAction(
            'Atualizar modelos',
            self,
        )
        refresh_templates_action.setShortcut("F5")
        refresh_templates_action.triggered.connect(
            self._load_templates
        )
        templates_submenu.addAction(
            refresh_templates_action
        )

        self.favorite_menu_action = QAction(
            'Adicionar modelo selecionado aos favoritos',
            self,
        )
        self.favorite_menu_action.triggered.connect(
            self._toggle_selected_favorite
        )
        templates_submenu.addAction(
            self.favorite_menu_action
        )

        favorites_action = QAction(
            'Abrir favoritos',
            self,
        )
        favorites_action.setShortcut(
            "Ctrl+Shift+F"
        )
        favorites_action.triggered.connect(
            self._show_favorites_page
        )
        templates_submenu.addAction(
            favorites_action
        )

        conversion_submenu = tools_menu.addMenu(
            'Converter arquivos'
        )

        docx_to_pdf_action = QAction(
            'DOCX para PDF',
            self,
        )
        docx_to_pdf_action.triggered.connect(
            lambda: self._show_converter_page(
                "docx_to_pdf"
            )
        )
        conversion_submenu.addAction(
            docx_to_pdf_action
        )

        pdf_to_docx_action = QAction(
            'PDF para DOCX',
            self,
        )
        pdf_to_docx_action.triggered.connect(
            lambda: self._show_converter_page(
                "pdf_to_docx"
            )
        )
        conversion_submenu.addAction(
            pdf_to_docx_action
        )

        profiles_submenu = tools_menu.addMenu(
            'Perfis de preenchimento'
        )

        save_profile_action = QAction(
            'Salvar dados atuais como perfil',
            self,
        )
        save_profile_action.triggered.connect(
            self._save_profile
        )
        profiles_submenu.addAction(
            save_profile_action
        )

        manage_profiles_action = QAction(
            'Gerenciar perfis',
            self,
        )
        manage_profiles_action.triggered.connect(
            self._manage_profiles
        )
        profiles_submenu.addAction(
            manage_profiles_action
        )

        backup_submenu = tools_menu.addMenu(
            'Backup'
        )

        create_backup_action = QAction(
            'Criar backup ZIP',
            self,
        )
        create_backup_action.triggered.connect(
            self._create_backup
        )
        backup_submenu.addAction(
            create_backup_action
        )

        restore_backup_action = QAction(
            'Restaurar backup ZIP',
            self,
        )
        restore_backup_action.triggered.connect(
            self._restore_backup
        )
        backup_submenu.addAction(
            restore_backup_action
        )

        self.dark_mode_action = QAction(
            'Modo escuro',
            self,
        )
        self.dark_mode_action.setCheckable(True)
        self.dark_mode_action.setChecked(
            self.theme_manager.current_theme()
            == ThemeManager.DARK
        )
        self.dark_mode_action.toggled.connect(
            self._set_dark_mode
        )
        view_menu.addAction(
            self.dark_mode_action
        )

        self.sidebar_action = QAction(
            'Mostrar barra lateral',
            self,
        )
        self.sidebar_action.setCheckable(True)
        self.sidebar_action.setChecked(True)
        self.sidebar_action.toggled.connect(
            lambda checked: self.sidebar.setVisible(
                checked
            )
        )
        view_menu.addAction(
            self.sidebar_action
        )

        tutorial_action = QAction(
            'Tutorial do aplicativo',
            self,
        )
        tutorial_action.setShortcut("F1")
        tutorial_action.triggered.connect(
            self._show_tutorial_page
        )
        help_menu.addAction(
            tutorial_action
        )

        guide_action = QAction(
            'Guia de marcadores e campos',
            self,
        )
        guide_action.triggered.connect(
            self._show_placeholder_guide
        )
        help_menu.addAction(
            guide_action
        )

        help_menu.addSeparator()

        about_action = QAction(
            'Sobre',
            self,
        )
        about_action.triggered.connect(
            self._show_about
        )
        help_menu.addAction(
            about_action
        )

    def _create_interface(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        outer.setSpacing(0)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        body_layout.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.page_changed.connect(
            self._change_page
        )
        self.pages = QStackedWidget()

        self.generate_page = (
            self._create_generate_page()
        )
        self.templates_page = (
            self._create_templates_page()
        )
        self.recent_page = (
            self._create_recent_page()
        )
        self.favorites_page = (
            self._create_favorites_page()
        )
        self.archive_page = (
            self._create_archive_page()
        )
        self.settings_page = (
            self._create_settings_page()
        )
        self.converter_page = (
            FileConverterPage()
        )
        self.converter_page.conversion_completed.connect(
            self._conversion_completed
        )
        self.tutorial_page = TutorialPage()
        self.tutorial_page.navigate_requested.connect(
            self._navigate_from_tutorial
        )
        self.home_page = HomePage()
        self.home_page.navigate_requested.connect(
            self._navigate_from_home
        )

        for page in (
            self.generate_page,
            self.templates_page,
            self.recent_page,
            self.favorites_page,
            self.archive_page,
            self.settings_page,
            self.converter_page,
            self.tutorial_page,
            self.home_page,
        ):
            self.pages.addWidget(page)

        body_layout.addWidget(
            self.sidebar
        )
        body_layout.addWidget(
            self.pages,
            1,
        )
        outer.addWidget(
            body,
            1,
        )
        self.setCentralWidget(
            central
        )

        home_index = self.pages.indexOf(
            self.home_page
        )
        self.sidebar.select_page(
            home_index
        )
        self.pages.setCurrentIndex(
            home_index
        )

    def _create_generate_page(self) -> QWidget:
        page = QWidget()

        self.generate_scroll = QScrollArea()
        self.generate_scroll.setWidgetResizable(True)
        self.generate_scroll.setFrameShape(
            QFrame.Shape.NoFrame
        )

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            22,
            20,
            22,
            24,
        )
        layout.setSpacing(14)

        selector = QFrame()
        selector.setObjectName(
            "generateTemplateBar"
        )
        selector_layout = QHBoxLayout(
            selector
        )
        selector_layout.setContentsMargins(
            12,
            10,
            12,
            10,
        )
        selector_layout.setSpacing(8)

        selector_label = HelpLabel(
            'Modelo',
            'Escolha do modelo',
            (
                '<p>Selecione o modelo que será usado para montar o formulário.</p>'
                '<p>Na página <b>Modelos</b>, também é possível clicar duas vezes '
                'em um item para abri-lo diretamente aqui.</p>'
                '<p>O Padroniza mantém um rascunho separado para cada modelo.</p>'
            ),
        )
        selector_label.label.setObjectName(
            "templateSelectorLabel"
        )
        selector_layout.addWidget(
            selector_label
        )

        self.template_combo = QComboBox()
        self.template_combo.setMinimumWidth(
            360
        )
        self.template_combo.currentIndexChanged.connect(
            self._render_selected_template
        )
        selector_layout.addWidget(
            self.template_combo,
            1,
        )

        self.favorite_button = QPushButton("☆")
        self.favorite_button.setObjectName(
            "templateFavoriteButton"
        )
        self.favorite_button.setCheckable(True)
        self.favorite_button.setFixedWidth(42)
        self.favorite_button.setToolTip(
            "Adicionar modelo selecionado aos favoritos"
        )
        self.favorite_button.clicked.connect(
            self._favorite_button_clicked
        )
        selector_layout.addWidget(
            self.favorite_button
        )
        layout.addWidget(selector)

        self.draft_banner = QFrame()
        self.draft_banner.setObjectName(
            "draftResumeBanner"
        )
        draft_layout = QHBoxLayout(
            self.draft_banner
        )
        draft_layout.setContentsMargins(
            14,
            11,
            12,
            11,
        )
        draft_layout.setSpacing(10)

        draft_text_layout = QVBoxLayout()
        draft_text_layout.setSpacing(2)
        self.draft_title_label = QLabel(
            "Há um preenchimento em andamento"
        )
        self.draft_title_label.setObjectName(
            "draftResumeTitle"
        )
        self.draft_message_label = QLabel()
        self.draft_message_label.setObjectName(
            "draftResumeText"
        )
        self.draft_message_label.setWordWrap(True)
        draft_text_layout.addWidget(
            self.draft_title_label
        )
        draft_text_layout.addWidget(
            self.draft_message_label
        )
        draft_layout.addLayout(
            draft_text_layout,
            1,
        )

        self.draft_discard_button = QPushButton(
            "Começar do zero"
        )
        self.draft_continue_button = QPushButton(
            "Continuar preenchimento"
        )
        self.draft_continue_button.setObjectName(
            "primaryButton"
        )
        self.draft_discard_button.clicked.connect(
            self._discard_saved_draft
        )
        self.draft_continue_button.clicked.connect(
            self._continue_saved_draft
        )
        draft_layout.addWidget(
            self.draft_discard_button
        )
        draft_layout.addWidget(
            self.draft_continue_button
        )
        self.draft_banner.hide()
        layout.addWidget(self.draft_banner)

        self.generate_empty_state = EmptyState(
            'Nenhum modelo disponível',
            (
                'Crie ou importe um modelo DOCX para montar o primeiro '
                'formulário e gerar documentos padronizados.'
            ),
            icon='＋',
        )
        self.generate_empty_state.add_action(
            'Criar ou importar modelo',
            self._open_template_manager,
            primary=True,
        )
        self.generate_empty_state.add_action(
            'Ver tutorial',
            self._show_tutorial_page,
        )
        self.generate_empty_state.hide()
        layout.addWidget(self.generate_empty_state, 1)

        self.template_header = TemplateHeader()
        layout.addWidget(self.template_header)

        self.profile_group = QGroupBox(
            'Perfil de preenchimento'
        )
        profile_row = QHBoxLayout(
            self.profile_group
        )
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(280)
        self.apply_profile_button = QPushButton(
            'Aplicar perfil'
        )
        self.save_profile_button = QPushButton(
            'Salvar dados atuais como perfil'
        )
        self.manage_profiles_button = QPushButton(
            'Gerenciar perfis'
        )
        self.apply_profile_button.clicked.connect(
            self._apply_selected_profile
        )
        self.save_profile_button.clicked.connect(
            self._save_profile
        )
        self.manage_profiles_button.clicked.connect(
            self._manage_profiles
        )
        profile_row.addWidget(
            self.profile_combo,
            1,
        )
        self.profile_help_button = HelpIconButton(
            'Perfis de preenchimento',
            (
                '<p>Perfis guardam dados reutilizados com frequência, como '
                'informações da empresa, representante e contato.</p>'
                '<p><b>Aplicar perfil</b> preenche somente os campos associados '
                'às chaves disponíveis no perfil. Revise os dados antes de gerar.</p>'
            ),
        )
        profile_row.addWidget(
            self.profile_help_button
        )
        profile_row.addWidget(
            self.apply_profile_button
        )
        profile_row.addWidget(
            self.save_profile_button
        )
        profile_row.addWidget(
            self.manage_profiles_button
        )
        layout.addWidget(self.profile_group)

        self.document_form = DocumentForm()
        self.document_form.values_changed.connect(
            self._form_values_changed
        )
        layout.addWidget(self.document_form)
        layout.addStretch()
        self.generate_scroll.setWidget(content)

        self.generate_action_bar = QFrame()
        self.generate_action_bar.setObjectName(
            "generateActionBar"
        )
        action_layout = QVBoxLayout(
            self.generate_action_bar
        )
        action_layout.setContentsMargins(
            16,
            10,
            16,
            12,
        )
        action_layout.setSpacing(8)

        status_row = QHBoxLayout()
        status_row.setSpacing(10)
        self.generate_context_label = QLabel()
        self.generate_context_label.setObjectName(
            "generateContextLabel"
        )
        self.generate_context_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        status_row.addWidget(
            self.generate_context_label,
            1,
        )

        self.draft_save_label = QLabel(
            "Rascunho salvo automaticamente"
        )
        self.draft_save_label.setObjectName(
            "draftSaveStatus"
        )
        status_row.addWidget(
            self.draft_save_label
        )
        action_layout.addLayout(status_row)

        validation_row = QHBoxLayout()
        validation_row.setSpacing(8)
        self.validation_summary_label = QLabel()
        self.validation_summary_label.setObjectName(
            "generationValidationStatus"
        )
        validation_row.addWidget(
            self.validation_summary_label
        )
        self.validation_help_button = HelpIconButton(
            'Validação e pendências',
            (
                '<p>O formulário verifica campos obrigatórios e preenchimentos com '
                'formato inválido antes da geração.</p>'
                '<p>Use <b>Revisar pendências</b> para ir diretamente ao próximo '
                'campo que precisa de atenção. Os campos problemáticos ficam '
                'destacados no formulário.</p>'
            ),
        )
        validation_row.addWidget(
            self.validation_help_button
        )

        self.review_issues_button = QPushButton(
            "Revisar pendências"
        )
        self.review_issues_button.clicked.connect(
            self._review_next_issue
        )
        validation_row.addWidget(
            self.review_issues_button
        )
        validation_row.addStretch()
        action_layout.addLayout(validation_row)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.clear_button = QPushButton('Limpar')
        self.sample_button = QPushButton(
            'Dados de exemplo'
        )
        self.generate_button = QPushButton(
            'Gerar DOCX'
        )
        self.pdf_button = QPushButton(
            'Gerar PDF'
        )
        self.generation_formats_help_button = HelpIconButton(
            'Formatos e destino',
            (
                '<p><b>Gerar DOCX</b> cria um arquivo editável. '
                '<b>Gerar PDF</b> cria uma versão pronta para compartilhar.</p>'
                '<p>O destino segue a pasta e a regra de conflito definidas em '
                '<b>Configurações → Saída padrão</b>.</p>'
            ),
        )
        self.generate_button.setObjectName(
            "primaryButton"
        )
        self.pdf_button.setObjectName(
            "secondaryActionButton"
        )

        self.clear_button.clicked.connect(
            self._clear_form
        )
        self.sample_button.clicked.connect(
            self._load_sample_data
        )
        self.generate_button.clicked.connect(
            self._generate_document
        )
        self.pdf_button.clicked.connect(
            self._generate_pdf_document
        )

        button_row.addWidget(self.clear_button)
        button_row.addWidget(self.sample_button)
        button_row.addWidget(self.generate_button)
        button_row.addWidget(self.pdf_button)
        button_row.addWidget(
            self.generation_formats_help_button
        )
        action_layout.addLayout(button_row)

        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.addWidget(
            self.generate_scroll,
            1,
        )
        page_layout.addWidget(
            self.generate_action_bar
        )
        return page

    def _create_templates_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        row = QHBoxLayout()
        heading = QLabel('Modelos')
        heading.setObjectName("pageTitle")
        row.addWidget(heading)
        row.addWidget(
            HelpIconButton(
                'Biblioteca de modelos',
                (
                    '<p>Clique duas vezes em um modelo para selecioná-lo e '
                    'abri-lo diretamente na página <b>Gerar</b>.</p>'
                    '<p>Use o Gerenciador para criar, editar, importar, exportar, '
                    'diagnosticar, arquivar ou excluir modelos.</p>'
                ),
            )
        )
        row.addStretch()
        manage = QPushButton('Abrir Gerenciador de Modelos')
        manage.setObjectName("primaryButton")
        manage.clicked.connect(self._open_template_manager)
        row.addWidget(manage)
        self.template_overview_table = self._make_table(
            ['Nome', 'Categoria', 'Versão', 'Campos', 'DOCX de origem'],
            [300, 180, 90, 90, 420],
        )
        self.template_overview_table.itemDoubleClicked.connect(
            self._open_template_from_overview
        )
        layout.addLayout(row)
        layout.addWidget(
            QLabel(
                'Clique duas vezes em um modelo para usá-lo na página Gerar. '
                'Use o Gerenciador de Modelos para editar, importar ou diagnosticar modelos.'
            )
        )
        self.templates_empty_state = EmptyState(
            'Sua biblioteca de modelos está vazia',
            (
                'Importe um DOCX existente ou crie um modelo para começar. '
                'O Padroniza analisará os marcadores e ajudará a configurar os campos.'
            ),
            icon='▦',
        )
        self.templates_empty_state.add_action(
            'Criar ou importar modelo',
            self._open_template_manager,
            primary=True,
        )
        self.templates_empty_state.add_action(
            'Aprender sobre modelos',
            self._show_tutorial_page,
        )
        layout.addWidget(self.templates_empty_state, 1)
        layout.addWidget(self.template_overview_table, 1)
        return page

    def _create_recent_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading_row = QHBoxLayout()
        heading = QLabel('Documentos recentes')
        heading.setObjectName("pageTitle")
        heading_row.addWidget(heading)
        heading_row.addWidget(
            HelpIconButton(
                'Histórico de documentos',
                (
                    '<p>O histórico guarda o modelo, os dados usados, o caminho '
                    'do resultado e, quando disponíveis, o processo e o perfil.</p>'
                    '<p><b>Gerar novamente</b> repete a saída com os mesmos dados. '
                    '<b>Editar dados anteriores</b> devolve os dados ao formulário.</p>'
                    '<p>Remover um registro do histórico não exclui o arquivo gerado.</p>'
                ),
            )
        )
        heading_row.addStretch()
        self.recent_table = self._make_table(
            ['Criado em', 'Documento', 'Modelo', 'Processo', 'Perfil', 'PDF', 'Caminho de saída'],
            [160, 230, 190, 150, 150, 60, 420],
        )
        self.recent_table.itemDoubleClicked.connect(lambda _item: self._open_recent_document())
        self.recent_empty_state = EmptyState(
            'Nenhum documento gerado ainda',
            (
                'Os documentos criados aparecerão aqui com atalhos para abrir, '
                'reutilizar os dados ou gerar uma nova versão.'
            ),
            icon='▤',
        )
        self.recent_empty_state.add_action(
            'Gerar primeiro documento',
            lambda: self._navigate_to_target('generate'),
            primary=True,
        )
        self.recent_actions_widget = QWidget()
        buttons = QHBoxLayout(self.recent_actions_widget)
        buttons.setContentsMargins(0, 0, 0, 0)
        for label, callback in (
            ('Abrir documento', self._open_recent_document),
            ('Abrir pasta', self._open_recent_folder),
            ('Gerar novamente', self._regenerate_recent),
            ('Editar dados anteriores', self._edit_recent_data),
            ('Usar outro modelo', self._use_recent_with_another_template),
            ('Remover registro', self._remove_recent_entry),
            ('Limpar histórico', self._clear_recent_history),
        ):
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(heading_row)
        layout.addWidget(self.recent_empty_state, 1)
        layout.addWidget(self.recent_table, 1)
        layout.addWidget(self.recent_actions_widget)
        return page

    def _create_favorites_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        row = QHBoxLayout()
        heading = QLabel('Modelos favoritos')
        heading.setObjectName("pageTitle")
        self.favorite_count_label = QLabel("0 favoritos")
        self.favorite_count_label.setObjectName("mutedText")
        row.addWidget(heading)
        row.addWidget(
            HelpIconButton(
                'Modelos favoritos',
                (
                    '<p>Favoritos deixam os modelos mais usados acessíveis em uma '
                    'lista separada.</p>'
                    '<p>Clique duas vezes em um item ou use <b>Usar modelo selecionado</b> '
                    'para abrir o formulário na página Gerar.</p>'
                ),
            )
        )
        row.addWidget(self.favorite_count_label)
        row.addStretch()
        self.use_favorite_button = QPushButton('Usar modelo selecionado')
        self.remove_favorite_button = QPushButton('Remover dos favoritos')
        self.use_favorite_button.clicked.connect(self._open_selected_favorite)
        self.remove_favorite_button.clicked.connect(self._remove_selected_favorite)
        row.addWidget(self.use_favorite_button)
        row.addWidget(self.remove_favorite_button)
        self.favorites_table = self._make_table(
            ['Nome', 'Categoria', 'Versão', 'Campos', 'DOCX de origem'],
            [300, 180, 90, 90, 420],
        )
        self.favorites_table.itemDoubleClicked.connect(lambda _item: self._open_selected_favorite())
        self.favorites_empty_state = EmptyState(
            'Nenhum modelo favorito',
            (
                'Marque com uma estrela os modelos usados com frequência. '
                'Eles ficarão reunidos nesta página para acesso rápido.'
            ),
            icon='☆',
        )
        self.favorites_empty_state.add_action(
            'Explorar modelos',
            lambda: self._navigate_to_target('templates'),
            primary=True,
        )
        layout.addLayout(row)
        layout.addWidget(self.favorites_empty_state, 1)
        layout.addWidget(self.favorites_table, 1)
        return page

    def _create_archive_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        heading_row = QHBoxLayout()
        heading = QLabel('Modelos arquivados')
        heading.setObjectName("pageTitle")
        heading_row.addWidget(heading)
        heading_row.addWidget(
            HelpIconButton(
                'Arquivamento de modelos',
                (
                    '<p>Arquivar remove o modelo da biblioteca ativa sem apagar seus '
                    'arquivos.</p>'
                    '<p>Use <b>Restaurar modelo selecionado</b> para devolvê-lo à '
                    'biblioteca. A exclusão permanente é feita no Gerenciador de Modelos.</p>'
                ),
            )
        )
        heading_row.addStretch()
        self.archive_table = self._make_table(
            ['Nome', 'Categoria', 'Versão', 'Pasta de arquivamento'],
            [300, 180, 90, 500],
        )
        self.archive_empty_state = EmptyState(
            'Nenhum modelo arquivado',
            (
                'Modelos arquivados permanecem guardados e podem ser restaurados '
                'quando voltarem a ser necessários.'
            ),
            icon='▣',
        )
        self.archive_empty_state.add_action(
            'Abrir Gerenciador de Modelos',
            self._open_template_manager,
            primary=True,
        )
        self.archive_actions_widget = QWidget()
        buttons = QHBoxLayout(self.archive_actions_widget)
        buttons.setContentsMargins(0, 0, 0, 0)
        restore_button = QPushButton('Restaurar modelo selecionado')
        open_button = QPushButton('Abrir pasta de arquivamento')
        refresh_button = QPushButton('Atualizar')
        restore_button.clicked.connect(self._restore_archived_template)
        open_button.clicked.connect(self._open_archive_folder)
        refresh_button.clicked.connect(self._refresh_archive_page)
        buttons.addWidget(restore_button)
        buttons.addWidget(open_button)
        buttons.addStretch()
        buttons.addWidget(refresh_button)
        layout.addLayout(heading_row)
        layout.addWidget(self.archive_empty_state, 1)
        layout.addWidget(self.archive_table, 1)
        layout.addWidget(self.archive_actions_widget)
        return page

    def _create_settings_page(self) -> QWidget:
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        heading_row = QHBoxLayout()
        heading = QLabel('Configurações do aplicativo')
        heading.setObjectName("pageTitle")
        heading_row.addWidget(heading)
        heading_row.addWidget(
            HelpIconButton(
                'Configurações do Padroniza',
                (
                    '<p>As alterações desta página são salvas automaticamente.</p>'
                    '<p>Algumas preferências, como o modo portátil, passam a valer '
                    'somente na próxima inicialização.</p>'
                ),
            )
        )
        heading_row.addStretch()
        layout.addLayout(heading_row)

        appearance = QGroupBox('Aparência e acessibilidade')
        appearance_layout = QVBoxLayout(appearance)
        appearance_row = QHBoxLayout()
        appearance_row.addWidget(QLabel('Tema:'))
        self.theme_combo = QComboBox()
        self.theme_combo.addItem('Claro', ThemeManager.LIGHT)
        self.theme_combo.addItem('Escuro', ThemeManager.DARK)
        self.theme_combo.currentIndexChanged.connect(self._theme_combo_changed)
        appearance_row.addWidget(self.theme_combo)
        appearance_row.addWidget(QLabel('Tamanho do texto:'))
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 18)
        self.font_size_spin.setSuffix(" pt")
        self.font_size_spin.valueChanged.connect(self._save_preferences)
        appearance_row.addWidget(self.font_size_spin)
        appearance_row.addWidget(
            HelpIconButton(
                'Aparência e acessibilidade',
                (
                    '<p>O tema altera as cores do aplicativo e o tamanho do texto '
                    'ajusta a interface inteira.</p>'
                    '<p>O alto contraste reforça bordas e estados de foco. A opção de '
                    'confirmação protege ações como excluir, arquivar e restaurar.</p>'
                ),
            )
        )
        appearance_row.addStretch()
        appearance_layout.addLayout(appearance_row)

        accessibility_row = QHBoxLayout()
        self.high_contrast_checkbox = QCheckBox('Modo de alto contraste')
        self.confirmations_checkbox = QCheckBox('Exibir confirmações para ações destrutivas')
        self.high_contrast_checkbox.toggled.connect(self._save_preferences)
        self.confirmations_checkbox.toggled.connect(self._save_preferences)
        accessibility_row.addWidget(self.high_contrast_checkbox)
        accessibility_row.addWidget(self.confirmations_checkbox)
        accessibility_row.addStretch()
        appearance_layout.addLayout(accessibility_row)
        appearance_note = QLabel(
            "A navegação por teclado está disponível em todo o aplicativo. "
            "Pressione Ctrl+K para pesquisa e comandos, F1 para o tutorial e Tab para navegar entre os controles."
        )
        appearance_note.setObjectName("mutedText")
        appearance_note.setWordWrap(True)
        appearance_layout.addWidget(appearance_note)
        layout.addWidget(appearance)

        output = QGroupBox('Saída padrão')
        output_layout = QVBoxLayout(output)
        output_row = QHBoxLayout()
        self.output_root_input = QLineEdit()
        browse_output = QPushButton('Procurar…')
        browse_output.clicked.connect(self._browse_output_root)
        self.output_root_input.editingFinished.connect(self._save_preferences)
        output_row.addWidget(self.output_root_input, 1)
        output_row.addWidget(browse_output)
        output_layout.addWidget(
            HelpLabel(
                'Pasta raiz de saída',
                'Pasta raiz de saída',
                (
                    '<p>É o local principal usado ao gerar documentos pelo formulário.</p>'
                    '<p>Modelos com padrão de pastas criam subpastas dentro deste local. '
                    'A conversão de arquivos continua salvando ao lado do arquivo original.</p>'
                ),
            )
        )
        output_layout.addLayout(output_row)

        conflict_row = QHBoxLayout()
        conflict_row.addWidget(
            HelpLabel(
                'Quando já existir um arquivo com o mesmo nome',
                'Conflitos de nome de arquivo',
                (
                    '<p><b>Adicionar _2, _3</b> preserva os arquivos anteriores.</p>'
                    '<p><b>Data e hora</b> cria um nome único. <b>Substituir</b> troca '
                    'o arquivo existente. <b>Perguntar sempre</b> decide caso a caso.</p>'
                ),
            )
        )
        self.output_conflict_combo = QComboBox()
        self.output_conflict_combo.addItem('Adicionar _2, _3 e assim por diante', "rename")
        self.output_conflict_combo.addItem('Adicionar data e hora', "timestamp")
        self.output_conflict_combo.addItem('Substituir o arquivo existente', "replace")
        self.output_conflict_combo.addItem('Perguntar sempre', "ask")
        self.output_conflict_combo.currentIndexChanged.connect(self._save_preferences)
        conflict_row.addWidget(self.output_conflict_combo)
        conflict_row.addStretch()
        output_layout.addLayout(conflict_row)

        self.converter_label = QLabel()
        self.converter_label.setObjectName("mutedText")
        output_layout.addWidget(self.converter_label)
        layout.addWidget(output)

        portable = QGroupBox('Modo portátil')
        portable_layout = QVBoxLayout(portable)
        self.portable_checkbox = QCheckBox(
            'Armazenar as configurações junto ao aplicativo para uso em USB ou pasta compartilhada'
        )
        self.portable_checkbox.toggled.connect(self._save_preferences)
        portable_note = QLabel(
            "A alteração do modo portátil será aplicada na próxima inicialização. "
            "Modelos, perfis, históricos e backups permanecem disponíveis nas pastas do projeto."
        )
        portable_note.setObjectName("mutedText")
        portable_note.setWordWrap(True)
        portable_row = QHBoxLayout()
        portable_row.addWidget(self.portable_checkbox)
        portable_row.addWidget(
            HelpIconButton(
                'Modo portátil',
                (
                    '<p>Armazena as preferências junto ao aplicativo, facilitando o '
                    'uso em pendrive ou pasta compartilhada.</p>'
                    '<p>A mudança é aplicada após reiniciar. Os modelos e dados do '
                    'projeto permanecem nas pastas atuais.</p>'
                ),
            )
        )
        portable_row.addStretch()
        portable_layout.addLayout(portable_row)
        portable_layout.addWidget(portable_note)
        layout.addWidget(portable)

        backup = QGroupBox('Backup e restauração')
        backup_layout = QVBoxLayout(backup)
        auto_row = QHBoxLayout()
        self.auto_backup_checkbox = QCheckBox('Criar um backup automático por dia')
        self.before_destructive_checkbox = QCheckBox('Criar backup antes de restaurar, arquivar ou excluir')
        auto_row.addWidget(self.auto_backup_checkbox)
        auto_row.addWidget(self.before_destructive_checkbox)
        auto_row.addWidget(
            HelpIconButton(
                'Backups automáticos e de segurança',
                (
                    '<p>O backup diário é criado uma vez por dia quando o aplicativo '
                    'é aberto.</p>'
                    '<p>O backup antes de ações destrutivas cria uma cópia de segurança '
                    'antes de restaurar, arquivar ou excluir conteúdo importante.</p>'
                ),
            )
        )
        auto_row.addStretch()
        backup_layout.addLayout(auto_row)

        backup_folder_row = QHBoxLayout()
        self.backup_folder_input = QLineEdit()
        browse_backups = QPushButton('Procurar…')
        browse_backups.clicked.connect(self._browse_backup_folder)
        backup_folder_row.addWidget(
            HelpLabel(
                'Pasta de backups',
                'Pasta de backups',
                (
                    '<p>Define onde os backups manuais, automáticos e de segurança '
                    'serão armazenados.</p>'
                    '<p>Escolha uma pasta com espaço disponível e inclua essa pasta '
                    'na sua rotina de cópia externa.</p>'
                ),
            )
        )
        backup_folder_row.addWidget(self.backup_folder_input, 1)
        backup_folder_row.addWidget(browse_backups)
        backup_layout.addLayout(backup_folder_row)

        backup_options = QHBoxLayout()
        backup_options.addWidget(
            HelpLabel(
                'Manter os mais recentes',
                'Retenção de backups',
                (
                    '<p>Limita quantos backups automáticos e de segurança permanecem '
                    'na pasta.</p>'
                    '<p>Os arquivos mais antigos são removidos quando o limite é '
                    'ultrapassado. Backups manuais com nomes diferentes não são afetados.</p>'
                ),
            )
        )
        self.backup_retention_spin = QSpinBox()
        self.backup_retention_spin.setRange(1, 100)
        self.backup_retention_spin.setSuffix(" backups")
        backup_options.addWidget(self.backup_retention_spin)
        backup_layout.addLayout(backup_options)

        for widget in (
            self.auto_backup_checkbox,
            self.before_destructive_checkbox,
            self.backup_folder_input,
            self.backup_retention_spin,
        ):
            if isinstance(widget, QLineEdit):
                widget.editingFinished.connect(self._save_preferences)
            elif isinstance(widget, QSpinBox):
                widget.valueChanged.connect(self._save_preferences)
            else:
                widget.toggled.connect(self._save_preferences)

        backup_buttons = QHBoxLayout()
        create_button = QPushButton('Criar backup ZIP')
        inspect_button = QPushButton('Ver conteúdo do backup')
        restore_button = QPushButton('Restaurar backup ZIP')
        create_button.clicked.connect(self._create_backup)
        inspect_button.clicked.connect(self._inspect_backup)
        restore_button.clicked.connect(self._restore_backup)
        backup_buttons.addWidget(create_button)
        backup_buttons.addWidget(inspect_button)
        backup_buttons.addWidget(restore_button)
        backup_buttons.addWidget(
            HelpIconButton(
                'Criar, revisar e restaurar backups',
                (
                    '<p><b>Criar backup ZIP</b> reúne modelos, dados e configurações.</p>'
                    '<p><b>Ver conteúdo</b> lista os arquivos sem restaurar. '
                    '<b>Restaurar</b> substitui os dados atuais pelos dados do ZIP e '
                    'deve ser usado com atenção.</p>'
                ),
            )
        )
        backup_buttons.addStretch()
        backup_layout.addLayout(backup_buttons)
        layout.addWidget(backup)

        audit_group = QGroupBox('Histórico de auditoria')
        audit_layout = QVBoxLayout(audit_group)
        self.audit_table = self._make_table(
            ['Data e hora', 'Ação', 'Descrição'],
            [180, 180, 650],
        )
        self.audit_empty_state = EmptyState(
            'Nenhuma atividade registrada',
            (
                'Gerações, backups, restaurações e alterações em modelos '
                'aparecerão aqui conforme o Padroniza for utilizado.'
            ),
            icon='≡',
        )
        self.audit_empty_state.setMinimumHeight(170)
        refresh_audit = QPushButton('Atualizar histórico de auditoria')
        refresh_audit.clicked.connect(self._refresh_audit_page)
        audit_actions = QHBoxLayout()
        audit_actions.addWidget(refresh_audit)
        audit_actions.addWidget(
            HelpIconButton(
                'Histórico de auditoria',
                (
                    '<p>Registra operações importantes, como geração, backup, '
                    'restauração e alterações em modelos.</p>'
                    '<p>É um histórico operacional do aplicativo; não altera nem '
                    'substitui os documentos gerados.</p>'
                ),
            )
        )
        audit_actions.addStretch()
        audit_layout.addWidget(self.audit_empty_state, 1)
        audit_layout.addWidget(self.audit_table, 1)
        audit_layout.addLayout(audit_actions)
        layout.addWidget(audit_group)
        layout.addStretch()

        scroll.setWidget(content)
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.addWidget(scroll)
        return page

    @staticmethod
    def _make_table(headers: list[str], widths: list[int]) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(32)
        table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate(widths):
            table.setColumnWidth(column, width)
        return table

    def _create_status_bar(self) -> None:
        self.status_message = QLabel('Pronto')
        self.template_count_label = QLabel("Modelos: 0")
        self.statusBar().addWidget(self.status_message)
        self.statusBar().addPermanentWidget(
            self.template_count_label
        )

    # Preferences/theme ---------------------------------------------------------
    def _load_preferences(self) -> None:
        self._loading_preferences = True
        theme = self.theme_manager.current_theme()
        index = self.theme_combo.findData(theme)
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentIndex(max(index, 0))
        self.theme_combo.blockSignals(False)
        self.output_root_input.setText(str(self._output_root()))

        self.font_size_spin.blockSignals(True)
        self.font_size_spin.setValue(int(self.settings.value("accessibility/font_size", 10) or 10))
        self.font_size_spin.blockSignals(False)
        self.high_contrast_checkbox.setChecked(
            bool(self.settings.value("accessibility/high_contrast", False, type=bool))
        )
        self.confirmations_checkbox.setChecked(
            bool(self.settings.value("ui/confirm_destructive", True, type=bool))
        )

        conflict = str(self.settings.value("output/conflict", "rename"))
        conflict_index = self.output_conflict_combo.findData(conflict)
        self.output_conflict_combo.setCurrentIndex(max(0, conflict_index))

        self.portable_checkbox.blockSignals(True)
        self.portable_checkbox.setChecked((self.project_root / PORTABLE_MARKER).exists())
        self.portable_checkbox.blockSignals(False)

        self.auto_backup_checkbox.setChecked(
            bool(self.settings.value("backup/automatic", False, type=bool))
        )
        self.before_destructive_checkbox.setChecked(
            bool(self.settings.value("backup/before_destructive_actions", True, type=bool))
        )
        self.backup_folder_input.setText(
            str(self.settings.value("backup/folder", str(self.project_root / "backups")))
        )
        self.backup_retention_spin.setValue(
            int(
                self.settings.value(
                    "backup/retention",
                    7,
                )
                or 7
            )
        )

        converter = available_converter()
        self.converter_label.setText(
            f"Conversão de documentos: {converter}. Nenhum aplicativo externo de escritório é necessário."
        )
        self._loading_preferences = False
        self.theme_manager.apply_theme(theme)

    def _save_preferences(self, *_args) -> None:
        if self._loading_preferences:
            return
        self.settings.setValue("output/root", self.output_root_input.text().strip())
        self.settings.setValue("output/conflict", self.output_conflict_combo.currentData() or "rename")
        self.settings.setValue("accessibility/font_size", self.font_size_spin.value())
        self.settings.setValue("accessibility/high_contrast", self.high_contrast_checkbox.isChecked())
        self.settings.setValue("ui/confirm_destructive", self.confirmations_checkbox.isChecked())
        self.settings.setValue("backup/automatic", self.auto_backup_checkbox.isChecked())
        self.settings.setValue("backup/before_destructive_actions", self.before_destructive_checkbox.isChecked())
        self.settings.setValue("backup/folder", self.backup_folder_input.text().strip())
        self.settings.setValue(
            "backup/retention",
            self.backup_retention_spin.value(),
        )
        self.settings.sync()
        set_portable_mode(self.project_root, self.portable_checkbox.isChecked())
        self.theme_manager.apply_theme(self.theme_manager.current_theme())

    def _browse_backup_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Selecionar pasta de backups",
            self.backup_folder_input.text().strip() or str(self.project_root),
        )
        if folder:
            self.backup_folder_input.setText(folder)
            self._save_preferences()

    def _output_root(self) -> Path:
        configured = str(
            self.settings.value(
                "output/root",
                "",
            )
            or ""
        ).strip()

        if configured:
            return Path(configured).expanduser()

        return self.default_output_dir

    def _browse_output_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Selecionar pasta raiz de saída", str(self._output_root()))
        if folder:
            self.output_root_input.setText(folder)
            self._save_preferences()

    def _theme_combo_changed(self) -> None:
        theme = self.theme_combo.currentData()
        if theme:
            self._apply_theme(str(theme))

    def _set_dark_mode(self, enabled: bool) -> None:
        self._apply_theme(ThemeManager.DARK if enabled else ThemeManager.LIGHT)

    def _apply_theme(self, theme: str) -> None:
        self.theme_manager.apply_theme(theme)
        dark = theme == ThemeManager.DARK
        self.dark_mode_action.blockSignals(True)
        self.dark_mode_action.setChecked(dark)
        self.dark_mode_action.blockSignals(False)
        index = self.theme_combo.findData(theme)
        if index >= 0:
            self.theme_combo.blockSignals(True)
            self.theme_combo.setCurrentIndex(index)
            self.theme_combo.blockSignals(False)

    # Templates ----------------------------------------------------------------
    def _load_templates(self) -> None:
        current_package = self._selected_template()
        current_id = (
            current_package.template_id
            if current_package is not None
            else None
        )
        if (
            self._active_template_id
            and self._form_dirty
            and not self._draft_choice_pending
        ):
            self.autosave_timer.stop()
            self._persist_current_draft(
                self._active_template_id
            )
            self._form_dirty = False
        self.templates = discover_templates(self.templates_dir)
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        selected_index = 0
        for index, package in enumerate(self.templates):
            self.template_combo.addItem(package.name, package.template_id)
            if package.template_id == current_id:
                selected_index = index
        if self.templates:
            self.template_combo.setCurrentIndex(selected_index)
        self.template_combo.blockSignals(False)

        enabled = bool(self.templates)
        for button in (
            self.generate_button,
            self.pdf_button,
            self.sample_button,
            self.clear_button,
        ):
            button.setEnabled(enabled)
        self.template_count_label.setText(f"Modelos: {len(self.templates)}")
        self.favorite_store.prune(package.template_id for package in self.templates)
        self._refresh_template_overview()
        self._refresh_favorites_page()
        self._refresh_archive_page()
        self._update_favorite_controls()

        if enabled:
            self.generate_empty_state.hide()
            self.template_header.show()
            self.profile_group.show()
            self.document_form.show()
            self._render_selected_template()
        else:
            self.generate_empty_state.show()
            self.template_header.hide()
            self.profile_group.hide()
            self.document_form.hide()
            self.document_form.set_template([], [])
            self.template_header.set_template(
                name='Nenhum modelo instalado',
                version="—",
                description='Use Gerenciar modelos para importar ou criar um modelo.',
                category="",
            )
            self._pending_draft = None
            self._set_draft_choice_pending(False)
            self._form_dirty = False
            self._refresh_generation_state()
            self.status_message.setText('Nenhum modelo carregado')

    def _selected_template(self) -> TemplatePackage | None:
        index = self.template_combo.currentIndex()
        return self.templates[index] if 0 <= index < len(self.templates) else None

    def _render_selected_template(self) -> None:
        package = self._selected_template()
        if package is None:
            return

        self.autosave_timer.stop()
        if (
            self._active_template_id
            and self._active_template_id != package.template_id
            and self._form_dirty
            and not self._draft_choice_pending
        ):
            self._persist_current_draft(
                self._active_template_id
            )

        self._active_template_id = package.template_id
        self._active_profile_id = None
        self._active_profile_name = ""
        self._form_dirty = False
        self._draft_choice_pending = False
        self._pending_draft = None
        self.template_header.set_template(
            name=package.name,
            version=package.version,
            description=package.description,
            category=package.category,
        )
        self.document_form.set_template(
            package.fields,
            package.config.get("sections", []),
        )
        self._offer_saved_draft(package)
        self._update_favorite_controls()
        self._refresh_generation_state()
        self.status_message.setText(
            f"Carregado: {package.name}"
        )

    def _refresh_template_overview(self) -> None:
        table = self.template_overview_table
        table.setRowCount(0)
        for package in self.templates:
            row = table.rowCount()
            table.insertRow(row)
            values = [package.name, package.category, package.version, str(len(package.fields)), str(package.source_path)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(
                        Qt.ItemDataRole.UserRole,
                        package.template_id,
                    )
                table.setItem(row, column, item)
        has_templates = bool(self.templates)
        self.templates_empty_state.setVisible(not has_templates)
        self.template_overview_table.setVisible(has_templates)
        if has_templates:
            self.template_overview_table.selectRow(0)

    def _open_template_from_overview(
        self,
        item: QTableWidgetItem,
    ) -> None:
        template_item = self.template_overview_table.item(
            item.row(),
            0,
        )
        template_id = (
            template_item.data(Qt.ItemDataRole.UserRole)
            if template_item is not None
            else None
        )
        if template_id and self._select_template_by_id(str(template_id)):
            self._navigate_to_target("generate")

    def _open_template_manager(self) -> None:
        dialog = TemplateManagerDialog(self.templates_dir, self.favorite_store, self)
        dialog.exec()
        self._load_templates()

    # Favorites ----------------------------------------------------------------
    def _favorite_button_clicked(self, checked: bool) -> None:
        package = self._selected_template()
        if package:
            self.favorite_store.set_favorite(package.template_id, checked)
            self._refresh_favorites_page()
            self._update_favorite_controls()
            show_toast(
                self,
                'Favoritos atualizados',
                (
                    f'{package.name} foi adicionado aos favoritos.'
                    if checked
                    else f'{package.name} foi removido dos favoritos.'
                ),
            )

    def _toggle_selected_favorite(self) -> None:
        package = self._selected_template()
        if package:
            favorite = self.favorite_store.toggle(package.template_id)
            self._refresh_favorites_page()
            self._update_favorite_controls()
            show_toast(
                self,
                'Favoritos atualizados',
                (
                    f'{package.name} foi adicionado aos favoritos.'
                    if favorite
                    else f'{package.name} foi removido dos favoritos.'
                ),
            )

    def _update_favorite_controls(self) -> None:
        package = self._selected_template()
        favorite = bool(
            package
            and self.favorite_store.is_favorite(
                package.template_id
            )
        )

        self.favorite_button.blockSignals(True)
        self.favorite_button.setEnabled(
            package is not None
        )
        self.favorite_button.setChecked(
            favorite
        )
        self.favorite_button.setText(
            "★" if favorite else "☆"
        )
        self.favorite_button.setToolTip(
            "Remover modelo selecionado dos favoritos"
            if favorite
            else "Adicionar modelo selecionado aos favoritos"
        )
        self.favorite_button.blockSignals(False)

        self.favorite_menu_action.setEnabled(
            package is not None
        )
        self.favorite_menu_action.setText(
            'Remover modelo selecionado dos favoritos'
            if favorite
            else 'Adicionar modelo selecionado aos favoritos'
        )

    def _refresh_favorites_page(self) -> None:
        if not hasattr(self, "favorites_table"):
            return
        by_id = {package.template_id: package for package in self.templates}
        favorites = [by_id[value] for value in self.favorite_store.favorite_ids() if value in by_id]
        self.favorites_table.setRowCount(0)
        for package in favorites:
            row = self.favorites_table.rowCount()
            self.favorites_table.insertRow(row)
            values = [package.name, package.category, package.version, str(len(package.fields)), str(package.source_path)]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, package.template_id)
                self.favorites_table.setItem(row, column, item)
        count = len(favorites)
        self.favorite_count_label.setText(
            f"{count} favorito" if count == 1 else f"{count} favoritos"
        )
        self.favorites_empty_state.setVisible(count == 0)
        self.favorites_table.setVisible(count > 0)
        self.use_favorite_button.setEnabled(count > 0)
        self.remove_favorite_button.setEnabled(count > 0)
        if count:
            self.favorites_table.selectRow(0)

    def _selected_favorite_id(self) -> str | None:
        row = self.favorites_table.currentRow()
        item = self.favorites_table.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return str(value) if value else None

    def _open_selected_favorite(self) -> None:
        template_id = self._selected_favorite_id()
        if template_id and self._select_template_by_id(template_id):
            self.sidebar.select_page(0)
            self.pages.setCurrentIndex(0)

    def _remove_selected_favorite(self) -> None:
        template_id = self._selected_favorite_id()
        if template_id:
            package = next(
                (item for item in self.templates if item.template_id == template_id),
                None,
            )
            self.favorite_store.remove(template_id)
            self._refresh_favorites_page()
            self._update_favorite_controls()
            show_toast(
                self,
                'Removido dos favoritos',
                (
                    f'{package.name} não aparece mais na lista de favoritos.'
                    if package is not None
                    else 'O modelo foi removido da lista de favoritos.'
                ),
            )

    def _show_favorites_page(self) -> None:
        self.sidebar.select_page(3)
        self.pages.setCurrentIndex(3)
        self._refresh_favorites_page()

    def _select_template_by_id(self, template_id: str) -> bool:
        for index, package in enumerate(self.templates):
            if package.template_id == template_id:
                self.template_combo.setCurrentIndex(index)
                return True
        return False

    # Profiles/drafts -----------------------------------------------------------
    def _refresh_profiles(self) -> None:
        current = self.profile_combo.currentData() if hasattr(self, "profile_combo") else None
        self.profile_combo.clear()
        self.profile_combo.addItem('Selecione um perfil salvo...', None)
        selected = 0
        for index, profile in enumerate(self.local_store.list_profiles(), start=1):
            self.profile_combo.addItem(
                f"{profile.get('name', '')} — {profile.get('category', '')}",
                str(profile.get("id", "")),
            )
            if str(profile.get("id", "")) == str(current):
                selected = index
        self.profile_combo.setCurrentIndex(selected)

    def _apply_selected_profile(self) -> None:
        profile_id = self.profile_combo.currentData()
        if not profile_id:
            return
        profile = self.local_store.get_profile(str(profile_id))
        if profile and isinstance(profile.get("values"), dict):
            self.document_form.apply_profile(profile["values"])
            self._active_profile_id = str(profile.get("id", ""))
            self._active_profile_name = str(profile.get("name", ""))
            self.status_message.setText(f"Perfil aplicado: {profile.get('name', '')}")

    def _save_profile(self) -> None:
        if self._selected_template() is None:
            return
        name, accepted = QInputDialog.getText(self, 'Salvar perfil de preenchimento', 'Nome do perfil:')
        if not accepted or not name.strip():
            return
        category, accepted = QInputDialog.getText(
            self,
            'Categoria do perfil',
            'Categoria:',
            text="Empresa",
        )
        if not accepted:
            return
        try:
            self.local_store.save_profile(
                name=name.strip(),
                category=category.strip() or "Empresa",
                values=self.document_form.profile_payload(),
            )
        except Exception as exc:
            QMessageBox.critical(self, 'Não foi possível salvar o perfil', str(exc))
            return
        self._refresh_profiles()
        self.status_message.setText(f"Perfil salvo: {name.strip()}")
        show_toast(
            self,
            'Perfil salvo',
            f'O perfil {name.strip()} está disponível para novos preenchimentos.',
        )

    def _manage_profiles(self) -> None:
        ProfileManagerDialog(self.local_store, self).exec()
        self._refresh_profiles()

    def _form_values_changed(self) -> None:
        if self._restoring_draft:
            return
        self._form_dirty = True
        self._schedule_draft_save()
        self._refresh_generation_state()

    def _schedule_draft_save(self) -> None:
        if (
            not self._restoring_draft
            and not self._draft_choice_pending
        ):
            self.draft_save_label.setText(
                "Salvando rascunho…"
            )
            self.autosave_timer.start()

    def _persist_current_draft(
        self,
        template_id: str,
    ) -> None:
        values = self.document_form.current_values()
        if self.document_form.has_meaningful_values(values):
            self.local_store.save_draft(
                template_id,
                values,
            )
        else:
            self.local_store.delete_draft(
                template_id
            )

    def _save_current_draft(self) -> None:
        package = self._selected_template()
        if (
            package is None
            or package.template_id
            != self._active_template_id
            or self._draft_choice_pending
            or not self._form_dirty
        ):
            return

        self._persist_current_draft(
            package.template_id
        )
        if self.document_form.has_meaningful_values():
            saved_at = datetime.now().strftime(
                "%H:%M"
            )
            self.draft_save_label.setText(
                f"Rascunho salvo às {saved_at}"
            )
            self.status_message.setText(
                "Rascunho salvo automaticamente"
            )
        else:
            self.draft_save_label.setText(
                "Sem rascunho pendente"
            )
        self._form_dirty = False

    def _offer_saved_draft(
        self,
        package: TemplatePackage,
    ) -> None:
        draft = self.local_store.load_draft(
            package.template_id
        )
        values = (
            draft.get("values")
            if isinstance(draft, dict)
            else None
        )
        if (
            not isinstance(values, dict)
            or not self.document_form.has_meaningful_values(
                values
            )
        ):
            if isinstance(draft, dict):
                self.local_store.delete_draft(
                    package.template_id
                )
            self._set_draft_choice_pending(False)
            self.draft_save_label.setText(
                "Salvamento automático ativo"
            )
            return

        self._pending_draft = draft
        self._set_draft_choice_pending(True)
        updated_at = self._friendly_draft_time(
            str(draft.get("updated_at", ""))
        )
        self.draft_message_label.setText(
            "Um rascunho deste modelo foi salvo"
            f" {updated_at}. Escolha como deseja continuar."
        )
        self.draft_save_label.setText(
            "Rascunho aguardando confirmação"
        )

    def _set_draft_choice_pending(
        self,
        pending: bool,
    ) -> None:
        self._draft_choice_pending = bool(pending)
        self.draft_banner.setVisible(
            self._draft_choice_pending
        )
        self.document_form.setEnabled(
            not self._draft_choice_pending
        )
        self.profile_group.setEnabled(
            not self._draft_choice_pending
        )

    def _continue_saved_draft(self) -> None:
        package = self._selected_template()
        draft = self._pending_draft
        values = (
            draft.get("values")
            if isinstance(draft, dict)
            else None
        )
        if package is None or not isinstance(values, dict):
            self._set_draft_choice_pending(False)
            self._refresh_generation_state()
            return

        self._set_draft_choice_pending(False)
        self._restoring_draft = True
        try:
            self.document_form.set_values(
                values,
                emit_signal=False,
            )
        finally:
            self._restoring_draft = False
        self._pending_draft = None
        self._form_dirty = False
        self.draft_save_label.setText(
            "Rascunho retomado"
        )
        self._refresh_generation_state()
        self.status_message.setText(
            "Preenchimento anterior restaurado"
        )

    def _discard_saved_draft(self) -> None:
        package = self._selected_template()
        if package is not None:
            self.local_store.delete_draft(
                package.template_id
            )
        self._pending_draft = None
        self._set_draft_choice_pending(False)
        self._form_dirty = False
        self.draft_save_label.setText(
            "Novo preenchimento"
        )
        self._refresh_generation_state()
        self.status_message.setText(
            "Novo preenchimento iniciado"
        )

    @staticmethod
    def _friendly_draft_time(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return "anteriormente"
        if parsed.date() == date.today():
            return f"hoje às {parsed.strftime('%H:%M')}"
        return f"em {parsed.strftime('%d/%m/%Y às %H:%M')}"

    # Validation/preview/generation --------------------------------------------
    def _clear_form(self) -> None:
        package = self._selected_template()
        if package is None or self._draft_choice_pending:
            return

        if (
            self.document_form.has_meaningful_values()
            and bool(
                self.settings.value(
                    "ui/confirm_destructive",
                    True,
                    type=bool,
                )
            )
        ):
            answer = QMessageBox.question(
                self,
                'Limpar formulário',
                'Remover todos os dados preenchidos neste modelo?',
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self._restoring_draft = True
        try:
            self.document_form.clear_values()
        finally:
            self._restoring_draft = False
        self.autosave_timer.stop()
        self.local_store.delete_draft(
            package.template_id
        )
        self._form_dirty = False
        self._active_profile_id = None
        self._active_profile_name = ""
        self.draft_save_label.setText(
            "Sem rascunho pendente"
        )
        self._refresh_generation_state()
        self.status_message.setText(
            'Formulário limpo'
        )

    def _refresh_generation_state(self) -> None:
        package = self._selected_template()
        if package is None:
            self._validation_issues = []
            self.document_form.set_validation_issues([])
            self.generate_context_label.setText(
                "Nenhum modelo selecionado"
            )
            self.validation_summary_label.setText(
                "Selecione um modelo para começar"
            )
            self.validation_summary_label.setProperty(
                "validationState",
                "blocked",
            )
            self.review_issues_button.hide()
            for button in (
                self.clear_button,
                self.sample_button,
                self.generate_button,
                self.pdf_button,
            ):
                button.setEnabled(False)
            self._repolish_widget(
                self.validation_summary_label
            )
            return

        values = self.document_form.current_values()
        filename = self._planned_filename_preview(
            package,
            values,
        )
        self.generate_context_label.setText(
            f"{package.name}  •  {filename}"
        )
        self.generate_context_label.setToolTip(
            f"Modelo selecionado: {package.name}\n"
            f"Nome previsto: {filename}"
        )

        if self._draft_choice_pending:
            self._validation_issues = []
            self.document_form.set_validation_issues([])
            self.validation_summary_label.setText(
                "Escolha como continuar o rascunho"
            )
            self.validation_summary_label.setProperty(
                "validationState",
                "warning",
            )
            self.review_issues_button.hide()
            ready = False
        else:
            issues = self.document_form.validation_issues(
                values
            )
            self._validation_issues = issues
            self.document_form.set_validation_issues(
                issues
            )
            self._validation_issue_index = min(
                self._validation_issue_index,
                max(0, len(issues) - 1),
            )

            missing_count = sum(
                1
                for issue in issues
                if issue.get("kind") == "missing"
            )
            invalid_count = len(issues) - missing_count
            if not issues:
                self.validation_summary_label.setText(
                    "Pronto para gerar"
                )
                self.validation_summary_label.setProperty(
                    "validationState",
                    "ready",
                )
                self.review_issues_button.hide()
                ready = True
            else:
                parts: list[str] = []
                if missing_count:
                    parts.append(
                        f"{missing_count} obrigatório"
                        if missing_count == 1
                        else f"{missing_count} obrigatórios"
                    )
                if invalid_count:
                    parts.append(
                        f"{invalid_count} inválido"
                        if invalid_count == 1
                        else f"{invalid_count} inválidos"
                    )
                self.validation_summary_label.setText(
                    "Pendências: " + " • ".join(parts)
                )
                self.validation_summary_label.setProperty(
                    "validationState",
                    "blocked",
                )
                self.review_issues_button.setText(
                    "Revisar pendência"
                    if len(issues) == 1
                    else f"Revisar {len(issues)} pendências"
                )
                self.review_issues_button.show()
                ready = False

        self._repolish_widget(
            self.validation_summary_label
        )
        self.clear_button.setEnabled(
            not self._draft_choice_pending
        )
        self.sample_button.setEnabled(
            not self._draft_choice_pending
        )
        self.generate_button.setEnabled(ready)
        self.pdf_button.setEnabled(ready)

        disabled_tip = (
            "Resolva as pendências indicadas antes de gerar."
            if self._validation_issues
            else "Escolha como continuar o rascunho."
        )
        for button in (
            self.generate_button,
            self.pdf_button,
        ):
            button.setToolTip(
                "" if ready else disabled_tip
            )

    def _planned_filename_preview(
        self,
        package: TemplatePackage,
        values: dict[str, Any],
    ) -> str:
        numbering = package.config.get(
            "numbering",
            {},
        )
        sequence: int | None = None
        if bool(numbering.get("enabled", False)):
            key = str(
                numbering.get(
                    "key",
                    package.template_id,
                )
            ) or package.template_id
            sequence = self.local_store.peek_sequence(
                key
            )
        filename = self._render_pattern(
            package.config.get("output", {}).get(
                "filename_pattern",
                package.output_filename,
            ),
            package,
            values,
            sequence,
        )
        filename = self._sanitize_filename(
            filename
        )
        if not filename.casefold().endswith(
            ".docx"
        ):
            filename += ".docx"
        return filename

    def _review_next_issue(self) -> None:
        self._refresh_generation_state()
        if not self._validation_issues:
            return

        index = self._validation_issue_index % len(
            self._validation_issues
        )
        issue = self._validation_issues[index]
        self._validation_issue_index = (
            index + 1
        ) % len(self._validation_issues)

        field_id = str(
            issue.get("field_id", "")
        )
        target = self.document_form.focus_field(
            field_id
        )
        if target is not None:
            self.generate_scroll.ensureWidgetVisible(
                target,
                24,
                90,
            )
        self.status_message.setText(
            str(issue.get("message", ""))
        )

    @staticmethod
    def _repolish_widget(widget: QWidget) -> None:
        style = widget.style()
        if style is None:
            return
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _load_sample_data(self) -> None:
        if (
            self._selected_template()
            and not self._draft_choice_pending
        ):
            self.document_form.load_sample_data()
            self._refresh_generation_state()
            self.status_message.setText(
                'Dados de exemplo carregados'
            )
            show_toast(
                self,
                'Dados de exemplo carregados',
                'Revise os dados antes de gerar o documento.',
                kind='info',
            )

    def _validate_fields(self) -> None:
        self._refresh_generation_state()
        if self._validation_issues:
            self._review_next_issue()
            QMessageBox.warning(
                self,
                'Validação',
                'Ainda existem campos obrigatórios ausentes ou preenchimentos inválidos. '
                'O primeiro campo foi destacado.',
            )
            return
        show_toast(
            self,
            'Formulário válido',
            'Todos os campos obrigatórios visíveis e seus formatos estão corretos.',
        )

    def _collect_form_values(self) -> dict[str, Any] | None:
        self._refresh_generation_state()
        if self._draft_choice_pending:
            self.status_message.setText(
                'Escolha como continuar o rascunho antes de gerar.'
            )
            return None
        if self._validation_issues:
            self._review_next_issue()
            return None
        try:
            return self.document_form.collect_values()
        except ValueError as exc:
            self.status_message.setText(str(exc))
            self._refresh_generation_state()
            return None

    def _generate_document(self) -> None:
        package = self._selected_template()
        if package is None:
            return

        values = self._collect_form_values()
        if values is None:
            return

        planned_path, _ = self._planned_output(
            package,
            values,
            consume_sequence=False,
        )
        filename, _ = QFileDialog.getSaveFileName(
            self,
            'Salvar documento DOCX',
            str(planned_path),
            "Documento do Word (*.docx)",
        )
        if not filename:
            return

        output_path = Path(filename)
        if output_path.suffix.lower() != ".docx":
            output_path = output_path.with_suffix(".docx")
        output_path = self._resolve_output_conflict(output_path)
        if output_path is None:
            return

        self._consume_sequence(package)

        result = self._generate_one(
            package,
            values,
            output_path,
        )
        if result is None:
            return

        self._finish_single_generation(
            package=package,
            saved_path=output_path,
            message_title="DOCX criado",
            message_text=f"DOCX:\n{output_path}",
        )

    def _generate_pdf_document(self) -> None:
        package = self._selected_template()
        if package is None:
            return

        values = self._collect_form_values()
        if values is None:
            return

        planned_docx, _ = self._planned_output(
            package,
            values,
            consume_sequence=False,
        )
        planned_pdf = planned_docx.with_suffix(".pdf")

        filename, _ = QFileDialog.getSaveFileName(
            self,
            'Salvar documento PDF',
            str(planned_pdf),
            'Documento PDF (*.pdf)',
        )
        if not filename:
            return

        output_path = Path(filename)
        if output_path.suffix.lower() != ".pdf":
            output_path = output_path.with_suffix(".pdf")
        output_path = self._resolve_output_conflict(output_path)
        if output_path is None:
            return

        self._consume_sequence(package)

        try:
            with tempfile.TemporaryDirectory(
                prefix="padroniza-pdf-"
            ) as temporary_folder:
                temporary_docx = (
                    Path(temporary_folder)
                    / f"{output_path.stem}.docx"
                )
                generate_docx(
                    package.source_path,
                    temporary_docx,
                    values,
                )
                convert_docx_to_pdf(
                    temporary_docx,
                    output_path,
                )
        except DocumentGenerationError as exc:
            QMessageBox.critical(
                self,
                'Falha na geração',
                str(exc),
            )
            self.status_message.setText(
                'Falha na geração'
            )
            return
        except PdfConversionError as exc:
            QMessageBox.critical(
                self,
                'Falha na geração do PDF',
                str(exc),
            )
            self.status_message.setText(
                'Falha na geração do PDF'
            )
            return

        record = {
            "template_id": package.template_id,
            "template_name": package.name,
            "template_version": package.version,
            "filename": output_path.name,
            "docx_path": "",
            "pdf_path": str(output_path),
            "zip_path": "",
            "values": values,
            "pdf_error": "",
            "created_at": datetime.now()
            .replace(microsecond=0)
            .isoformat(),
            **self._document_history_metadata(values),
        }
        document_id = self.local_store.add_recent(record)
        self.local_store.add_audit(
            "document_generated",
            output_path.name,
            {
                "document_id": document_id,
                "template_id": package.template_id,
                "path": str(output_path),
                "format": "pdf",
            },
        )

        self._finish_single_generation(
            package=package,
            saved_path=output_path,
            message_title="PDF criado",
            message_text=f"PDF:\n{output_path}",
        )

    def _finish_single_generation(
        self,
        *,
        package: TemplatePackage,
        saved_path: Path,
        message_title: str,
        message_text: str,
    ) -> None:
        self.autosave_timer.stop()
        self.local_store.delete_draft(
            package.template_id
        )
        self._form_dirty = False
        self.draft_save_label.setText(
            "Documento gerado — sem rascunho pendente"
        )
        self._refresh_generation_state()
        self._refresh_recent_page()
        self._refresh_audit_page()
        self.status_message.setText(
            f"Salvo: {saved_path.name}"
        )
        show_toast(
            self,
            message_title,
            message_text,
            duration=6000,
        )

    def _generate_one(
        self,
        package: TemplatePackage,
        values: dict[str, Any],
        output_path: Path,
    ) -> dict[str, Any] | None:
        try:
            generate_docx(
                package.source_path,
                output_path,
                values,
            )
        except DocumentGenerationError as exc:
            QMessageBox.critical(
                self,
                'Falha na geração',
                str(exc),
            )
            self.status_message.setText(
                'Falha na geração'
            )
            return None

        record = {
            "template_id": package.template_id,
            "template_name": package.name,
            "template_version": package.version,
            "filename": output_path.name,
            "docx_path": str(output_path),
            "pdf_path": "",
            "zip_path": "",
            "values": values,
            "pdf_error": "",
            "created_at": datetime.now()
            .replace(microsecond=0)
            .isoformat(),
            **self._document_history_metadata(values),
        }
        document_id = self.local_store.add_recent(
            record
        )
        self.local_store.add_audit(
            "document_generated",
            output_path.name,
            {
                "document_id": document_id,
                "template_id": package.template_id,
                "path": str(output_path),
            },
        )
        return {
            "document_id": document_id
        }

    def _document_history_metadata(self, values: dict[str, Any]) -> dict[str, str]:
        process_number = ""
        preferred = (
            "process.number",
            "process_number",
            "processo.numero",
            "processo",
        )
        for key in preferred:
            value = values.get(key)
            if value not in (None, ""):
                process_number = str(value)
                break
        if not process_number:
            for key, value in values.items():
                normalized = str(key).casefold()
                if "process" in normalized and ("number" in normalized or "numero" in normalized):
                    process_number = str(value)
                    break
        return {
            "process_number": process_number,
            "profile_id": self._active_profile_id or "",
            "profile_name": self._active_profile_name,
        }

    def _planned_output(
        self,
        package: TemplatePackage,
        values: dict[str, Any],
        *,
        consume_sequence: bool,
        override_root: Path | None = None,
    ) -> tuple[Path, int | None]:
        numbering = package.config.get("numbering", {})
        sequence: int | None = None
        if bool(numbering.get("enabled", False)):
            key = str(numbering.get("key", package.template_id)) or package.template_id
            sequence = (
                self.local_store.next_sequence(key)
                if consume_sequence
                else self.local_store.peek_sequence(key)
            )
        filename = self._render_pattern(
            package.config.get("output", {}).get("filename_pattern", package.output_filename),
            package,
            values,
            sequence,
        )
        filename = self._sanitize_filename(filename)
        if not filename.casefold().endswith(".docx"):
            filename += ".docx"

        root = Path(override_root or self._output_root())
        folder_pattern = str(package.config.get("output", {}).get("folder_pattern", "")).strip()
        if folder_pattern and override_root is None:
            # Split the pattern before rendering. Field values such as a CNPJ
            # may contain a slash and must remain inside one sanitized folder.
            for pattern_segment in re.split(r"[\\/]+", folder_pattern):
                rendered_segment = self._render_pattern(
                    pattern_segment, package, values, sequence
                )
                cleaned = self._sanitize_segment(rendered_segment)
                if cleaned and cleaned not in {".", ".."}:
                    root /= cleaned
        root.mkdir(parents=True, exist_ok=True)
        return root / filename, sequence

    def _consume_sequence(self, package: TemplatePackage) -> None:
        numbering = package.config.get("numbering", {})
        if bool(numbering.get("enabled", False)):
            key = str(numbering.get("key", package.template_id)) or package.template_id
            self.local_store.next_sequence(key)

    def _render_pattern(
        self,
        pattern: Any,
        package: TemplatePackage,
        values: dict[str, Any],
        sequence: int | None,
    ) -> str:
        result = str(pattern or "")
        padding = int(package.config.get("numbering", {}).get("padding", 4) or 4)
        tokens: dict[str, str] = {
            "template.name": package.name,
            "template.id": package.template_id,
            "template.version": package.version,
            "year": str(date.today().year),
            "sequence": str(sequence).zfill(padding) if sequence is not None else "",
        }
        for field_id, value in values.items():
            tokens[field_id] = 'Sim' if value is True else 'Não' if value is False else str(value or "")
        for key, value in tokens.items():
            result = result.replace(f"{{{{{key}}}}}", value)
            result = result.replace(f"{{{{date:{key}}}}}", value)
        return result

    def _resolve_output_conflict(self, path: Path) -> Path | None:
        path = Path(path)
        if not path.exists():
            return path
        mode = str(self.settings.value("output/conflict", "rename"))
        if mode == "replace":
            return path
        if mode == "timestamp":
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            return path.with_name(f"{path.stem}_{stamp}{path.suffix}")
        if mode == "ask":
            answer = QMessageBox.question(
                self,
                'O arquivo já existe',
                f"Substituir o arquivo existente?\n\n{path}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                return path
            if answer == QMessageBox.StandardButton.Cancel:
                return None
        return self._unique_output_path(path)

    @staticmethod
    def _unique_output_path(path: Path) -> Path:
        path = Path(path)
        if not path.exists():
            return path
        counter = 2
        while True:
            candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _sanitize_filename(value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*]', "-", str(value))
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
        return cleaned or "generated_document.docx"

    def closeEvent(self, event) -> None:
        self.autosave_timer.stop()
        if (
            self._active_template_id
            and self._form_dirty
            and not self._draft_choice_pending
        ):
            self._persist_current_draft(
                self._active_template_id
            )
        super().closeEvent(event)

    @staticmethod
    def _sanitize_segment(value: str) -> str:
        cleaned = re.sub(r'[<>:"/\\|?*]', "-", str(value))
        return re.sub(r"\s+", " ", cleaned).strip(" .")[:120]

    @staticmethod
    def _values_for_template(package: TemplatePackage, source_values: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for field in package.fields:
            field_id = str(field.get("id", ""))
            field_type = str(field.get("type", "text"))
            profile_key = str(field.get("profile_key", "")).strip()
            if field_id in source_values:
                result[field_id] = source_values[field_id]
            elif profile_key and profile_key in source_values:
                result[field_id] = source_values[profile_key]
            elif field_type == "checkbox":
                result[field_id] = False
            elif field_type == "date":
                result[field_id] = date.today().strftime("%d/%m/%Y")
            else:
                result[field_id] = ""
        return result

    @staticmethod
    def _missing_required_for_package(package: TemplatePackage, values: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        for field in package.fields:
            if not condition_matches(field.get("visible_when"), values):
                continue
            error = validate_field(field, values.get(str(field.get("id", ""))))
            if error:
                errors.append(error)
        return errors

    # Recent documents ----------------------------------------------------------
    def _refresh_recent_page(self) -> None:
        if not hasattr(self, "recent_table"):
            return
        self.recent_table.setRowCount(0)
        for record in self.local_store.list_recent():
            row = self.recent_table.rowCount()
            self.recent_table.insertRow(row)
            docx_path = str(record.get("docx_path", ""))
            pdf_path = str(record.get("pdf_path", ""))
            primary_path = docx_path or pdf_path
            values = [
                str(record.get("created_at", "")),
                str(record.get("filename", Path(primary_path).name)),
                str(record.get("template_name", record.get("template_id", ""))),
                str(record.get("process_number", "")),
                str(record.get("profile_name", "")),
                'Sim' if pdf_path else 'Não',
                primary_path,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, str(record.get("id", "")))
                self.recent_table.setItem(row, column, item)
        has_recent = self.recent_table.rowCount() > 0
        self.recent_empty_state.setVisible(not has_recent)
        self.recent_table.setVisible(has_recent)
        self.recent_actions_widget.setVisible(has_recent)
        if has_recent:
            self.recent_table.selectRow(0)

    def _selected_recent(self) -> dict[str, Any] | None:
        row = self.recent_table.currentRow()
        item = self.recent_table.item(row, 0) if row >= 0 else None
        record_id = str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""
        return self.local_store.get_recent(record_id) if record_id else None

    def _recent_output_path(
        self,
        record: dict[str, Any] | None,
    ) -> Path | None:
        if not record:
            return None

        raw_path = str(
            record.get("docx_path", "")
            or record.get("pdf_path", "")
        ).strip()
        return Path(raw_path) if raw_path else None

    def _open_recent_document(self) -> None:
        record = self._selected_recent()
        path = self._recent_output_path(record)
        if path and path.exists():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(
                    str(path.resolve())
                )
            )
        elif record:
            QMessageBox.warning(
                self,
                'Arquivo não encontrado',
                "O arquivo gerado não está mais "
                "no caminho registrado.",
            )

    def _open_recent_folder(self) -> None:
        record = self._selected_recent()
        path = self._recent_output_path(record)
        if path and path.parent.exists():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(
                    str(path.parent.resolve())
                )
            )

    def _edit_recent_data(self) -> None:
        record = self._selected_recent()
        if not record:
            return
        if not self._select_template_by_id(str(record.get("template_id", ""))):
            QMessageBox.warning(self, 'Modelo indisponível', 'O modelo usado por este registro não está instalado.')
            return
        self.document_form.set_values(record.get("values", {}))
        self.sidebar.select_page(0)
        self.pages.setCurrentIndex(0)

    def _regenerate_recent(self) -> None:
        record = self._selected_recent()
        if not record:
            return

        generate_pdf = bool(
            record.get("pdf_path")
            and not record.get("docx_path")
        )
        self._edit_recent_data()

        if generate_pdf:
            self._generate_pdf_document()
        else:
            self._generate_document()

    def _use_recent_with_another_template(self) -> None:
        record = self._selected_recent()
        if not record or not self.templates:
            return
        names = [package.name for package in self.templates]
        selected, accepted = QInputDialog.getItem(
            self,
            'Usar outro modelo',
            "Modelo:",
            names,
            0,
            False,
        )
        if not accepted:
            return
        index = names.index(selected)
        source_values = dict(record.get("values", {}))
        source_package = next(
            (package for package in self.templates if package.template_id == str(record.get("template_id", ""))),
            None,
        )
        if source_package is not None:
            for field in source_package.fields:
                field_id = str(field.get("id", ""))
                profile_key = str(field.get("profile_key", "")).strip()
                if profile_key and field_id in source_values:
                    source_values[profile_key] = source_values[field_id]

        self.template_combo.setCurrentIndex(index)
        target_package = self._selected_template()
        if target_package is not None:
            self.document_form.set_values(self._values_for_template(target_package, source_values))
        self.sidebar.select_page(0)
        self.pages.setCurrentIndex(0)

    def _remove_recent_entry(self) -> None:
        record = self._selected_recent()
        if record:
            self.local_store.delete_recent(str(record.get("id", "")))
            self._refresh_recent_page()
            show_toast(
                self,
                'Registro removido',
                'O documento foi removido do histórico. O arquivo continua no disco.',
                kind='info',
            )

    def _clear_recent_history(self) -> None:
        confirmed = True
        if bool(self.settings.value("ui/confirm_destructive", True, type=bool)):
            answer = QMessageBox.question(
                self,
                'Limpar histórico recente',
                'Remover todos os registros de documentos recentes? Os arquivos gerados não serão excluídos.',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            confirmed = answer == QMessageBox.StandardButton.Yes
        if confirmed:
            self.local_store.clear_recent()
            self._refresh_recent_page()
            show_toast(
                self,
                'Histórico limpo',
                'Os registros foram removidos. Os arquivos gerados não foram excluídos.',
                kind='info',
            )

    # Archive/audit/backup ------------------------------------------------------
    def _refresh_archive_page(self) -> None:
        if not hasattr(self, "archive_table"):
            return
        self.archive_table.setRowCount(0)
        for item in self.repository.list_archived_templates():
            row = self.archive_table.rowCount()
            self.archive_table.insertRow(row)
            values = [item["name"], item["category"], item["version"], str(item["folder"])]
            for column, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                if column == 0:
                    table_item.setData(Qt.ItemDataRole.UserRole, str(item["archive_id"]))
                self.archive_table.setItem(row, column, table_item)
        has_archived = self.archive_table.rowCount() > 0
        self.archive_empty_state.setVisible(not has_archived)
        self.archive_table.setVisible(has_archived)
        self.archive_actions_widget.setVisible(has_archived)
        if has_archived:
            self.archive_table.selectRow(0)

    def _selected_archive_id(self) -> str | None:
        row = self.archive_table.currentRow()
        item = self.archive_table.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return str(value) if value else None

    def _restore_archived_template(self) -> None:
        archive_id = self._selected_archive_id()
        if not archive_id:
            return
        try:
            template_id = self.repository.restore_archived_template(archive_id)
        except Exception as exc:
            QMessageBox.critical(self, 'Não foi possível restaurar o modelo', str(exc))
            return
        self.local_store.add_audit("template_restored", template_id, {})
        self._load_templates()
        self._select_template_by_id(template_id)
        show_toast(
            self,
            'Modelo restaurado',
            'O modelo voltou para a biblioteca ativa.',
        )

    def _open_archive_folder(self) -> None:
        archive_id = self._selected_archive_id()
        if archive_id:
            folder = self.repository.archive_dir / archive_id
            if folder.exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    def _refresh_audit_page(self) -> None:
        if not hasattr(self, "audit_table"):
            return
        self.audit_table.setRowCount(0)
        for entry in self.local_store.list_audit(limit=500):
            row = self.audit_table.rowCount()
            self.audit_table.insertRow(row)
            values = [entry.get("timestamp", ""), entry.get("action", ""), entry.get("description", "")]
            for column, value in enumerate(values):
                self.audit_table.setItem(row, column, QTableWidgetItem(str(value)))
        has_entries = self.audit_table.rowCount() > 0
        self.audit_empty_state.setVisible(not has_entries)
        self.audit_table.setVisible(has_entries)

    def _backup_configuration(
        self,
    ) -> tuple[Path, int]:
        folder = Path(
            str(
                self.settings.value(
                    "backup/folder",
                    str(
                        self.project_root
                        / "backups"
                    ),
                )
            )
        )
        retention = int(
            self.settings.value(
                "backup/retention",
                7,
            )
            or 7
        )
        return folder, retention

    def _create_backup(self) -> None:
        folder, _retention = (
            self._backup_configuration()
        )
        suggested = (
            folder
            / (
                "padroniza-backup-"
                f"{date.today().isoformat()}"
                ".zip"
            )
        )
        filename, _ = (
            QFileDialog.getSaveFileName(
                self,
                "Criar backup do Padroniza",
                str(suggested),
                "Arquivo ZIP (*.zip)",
            )
        )
        if not filename:
            return

        try:
            path = create_backup(
                self.project_root,
                Path(filename),
                reason="manual",
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Falha no backup",
                str(exc),
            )
            return

        self.local_store.add_audit(
            "backup_created",
            path.name,
            {
                "path": str(path),
            },
        )
        show_toast(
            self,
            'Backup criado',
            f'Salvo em:\n{path}',
            duration=6000,
        )

    def _choose_backup_archive(
        self,
        title: str,
    ) -> str:
        filename, _ = (
            QFileDialog.getOpenFileName(
                self,
                title,
                str(
                    self.backup_folder_input
                    .text()
                    .strip()
                ),
                "Arquivo ZIP (*.zip)",
            )
        )
        return filename

    def _read_backup_information(
        self,
        filename: str,
    ) -> dict[str, Any] | None:
        try:
            return inspect_backup(
                Path(filename)
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Não foi possível ler o backup",
                str(exc),
            )
            return None

    def _select_backup_information(
        self,
        title: str,
    ) -> tuple[
        str,
        dict[str, Any],
    ] | None:
        filename = (
            self._choose_backup_archive(
                title
            )
        )
        if not filename:
            return None

        information = (
            self._read_backup_information(
                filename
            )
        )
        if information is None:
            return None

        return filename, information

    def _inspect_backup(self) -> None:
        selection = (
            self._select_backup_information(
                "Ver conteúdo do backup"
            )
        )
        if selection is None:
            return

        _filename, information = selection
        BackupContentsDialog(
            information,
            self,
        ).exec()

    def _run_scheduled_backup_if_due(
        self,
    ) -> None:
        if not bool(
            self.settings.value(
                "backup/automatic",
                False,
                type=bool,
            )
        ):
            return

        last = str(
            self.settings.value(
                "backup/last_automatic_date",
                "",
            )
        )
        today = date.today().isoformat()
        if last == today:
            return

        folder, retention = (
            self._backup_configuration()
        )
        try:
            path = create_scheduled_backup(
                self.project_root,
                folder,
                retention=retention,
                reason="automatic",
            )
        except Exception as exc:
            self.status_message.setText(
                "Falha no backup automático: "
                f"{exc}"
            )
            return

        self.settings.setValue(
            "backup/last_automatic_date",
            today,
        )
        self.settings.sync()
        self.local_store.add_audit(
            "automatic_backup",
            path.name,
            {
                "path": str(path),
            },
        )
        self.status_message.setText(
            "Backup automático criado: "
            f"{path.name}"
        )

    def _create_pre_restore_backup(
        self,
    ) -> None:
        if not bool(
            self.settings.value(
                "backup/before_destructive_actions",
                True,
                type=bool,
            )
        ):
            return

        folder, retention = (
            self._backup_configuration()
        )
        create_scheduled_backup(
            self.project_root,
            folder,
            retention=retention,
            reason="before-restore",
        )

    def _restore_backup(self) -> None:
        selection = (
            self._select_backup_information(
                "Restaurar backup do Padroniza"
            )
        )
        if selection is None:
            return

        filename, information = selection

        BackupContentsDialog(
            information,
            self,
        ).exec()

        answer = QMessageBox.warning(
            self,
            "Restaurar backup",
            "A restauração substituirá os "
            "modelos, dados do aplicativo "
            "e configurações atuais. "
            "Deseja continuar?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if (
            answer
            != QMessageBox.StandardButton.Yes
        ):
            return

        try:
            self._create_pre_restore_backup()
            restore_backup(
                self.project_root,
                Path(filename),
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Falha na restauração",
                str(exc),
            )
            return

        self.local_store = LocalDataStore(
            self.data_dir
        )
        self.repository = (
            TemplateRepository(
                self.templates_dir
            )
        )
        self._load_preferences()
        self._load_templates()
        self._refresh_profiles()
        self._refresh_recent_page()
        self._refresh_archive_page()
        self._refresh_audit_page()
        show_toast(
            self,
            'Backup restaurado',
            'Os modelos, dados e configurações foram atualizados.',
            duration=6000,
        )

    def _show_converter_page(self, direction: str = "docx_to_pdf") -> None:
        index = self.pages.indexOf(self.converter_page)
        if index < 0:
            return
        self.sidebar.select_page(index)
        self.pages.setCurrentIndex(index)
        self.converter_page.focus_direction(direction)

    def _conversion_completed(
        self,
        direction: str,
        source: str,
        output: str,
    ) -> None:
        label = (
            'DOCX convertido para PDF'
            if direction == "docx_to_pdf"
            else 'PDF convertido para DOCX'
        )
        output_path = Path(output)
        self.status_message.setText(
            f"Convertido: {output_path.name}"
        )
        show_toast(
            self,
            'Conversão concluída',
            f'{output_path.name} foi criado com sucesso.',
        )
        self.local_store.add_audit(
            "file_converted",
            label,
            {
                "direction": direction,
                "source": source,
                "output": output,
            },
        )
        self._refresh_audit_page()

    # Navigation/help -----------------------------------------------------------
    def _global_search_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = [
            {"kind": "Comando", "name": 'Criar documento', "details": "Abrir a página Gerar", "action": "generate"},
            {"kind": "Comando", "name": 'Gerenciar modelos', "details": "Abrir a biblioteca de modelos", "action": "templates"},
            {"kind": "Comando", "name": 'Converter arquivos', "details": "Abrir a conversão de DOCX e PDF", "action": "converter"},
            {"kind": "Comando", "name": 'Configurações do aplicativo', "details": "Abrir as configurações", "action": "settings"},
            {"kind": "Comando", "name": 'Tutorial', "details": "Abrir o tutorial do aplicativo", "action": "tutorial"},
            {"kind": "Comando", "name": "Criar backup", "details": "Criar um backup ZIP", "callback": "backup"},
        ]
        favorite_ids = set(self.favorite_store.favorite_ids())
        for package in self.templates:
            records.append({
                "kind": "Modelo favorito" if package.template_id in favorite_ids else 'Modelo',
                "name": package.name,
                "details": f"{package.category} · {package.version} · {len(package.fields)} campos",
                "template_id": package.template_id,
                "path": str(package.source_path),
            })
        for item in self.local_store.list_recent():
            path = str(item.get("docx_path", "") or item.get("pdf_path", ""))
            records.append({
                "kind": "Documento",
                "name": str(item.get("filename", Path(path).name)),
                "details": f"{item.get('template_name', '')} · {item.get('process_number', '')} · {item.get('created_at', '')}",
                "recent_id": str(item.get("id", "")),
                "path": path,
            })
        for profile in self.local_store.list_profiles():
            records.append({
                "kind": 'Perfil',
                "name": str(profile.get("name", "")),
                "details": str(profile.get("category", "")),
                "profile_id": str(profile.get("id", "")),
                "action": "generate",
            })
        for archive in self.repository.list_archived_templates():
            records.append({
                "kind": "Modelo arquivado",
                "name": str(archive.get("name", archive.get("id", ""))),
                "details": str(archive.get("category", "")),
                "action": "archive",
                "path": str(archive.get("folder", "")),
            })
        return records

    def _show_global_search(self) -> None:
        dialog = GlobalSearchDialog(self._global_search_records(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_record:
            return
        record = dialog.selected_record
        if record.get("callback") == "backup":
            self._create_backup()
            return
        template_id = str(record.get("template_id", ""))
        if template_id:
            self._select_template_by_id(template_id)
            self._navigate_to_target("generate")
            return
        recent_id = str(record.get("recent_id", ""))
        if recent_id:
            self._navigate_to_target("recent")
            for row in range(self.recent_table.rowCount()):
                item = self.recent_table.item(row, 0)
                if item and str(item.data(Qt.ItemDataRole.UserRole) or "") == recent_id:
                    self.recent_table.selectRow(row)
                    break
            return
        profile_id = str(record.get("profile_id", ""))
        if profile_id:
            self._navigate_to_target("generate")
            index = self.profile_combo.findData(profile_id)
            if index >= 0:
                self.profile_combo.setCurrentIndex(index)
                self._apply_selected_profile()
            return
        action = str(record.get("action", ""))
        if action:
            self._navigate_to_target(action)

    def _show_tutorial_page(self) -> None:
        index = self.pages.indexOf(self.tutorial_page)
        if index < 0:
            return
        self.sidebar.select_page(index)
        self.pages.setCurrentIndex(index)

    def _navigate_from_home(
        self,
        target: str,
    ) -> None:
        if target == "search":
            self._show_global_search()
            return
        self._navigate_to_target(
            target
        )

    def _navigate_from_tutorial(
        self,
        target: str,
    ) -> None:
        self._navigate_to_target(
            target
        )

    def _navigate_to_target(
        self,
        target: str,
    ) -> None:
        page_map = {
            "home": self.home_page,
            "generate": self.generate_page,
            "templates": self.templates_page,
            "recent": self.recent_page,
            "favorites": self.favorites_page,
            "archive": self.archive_page,
            "settings": self.settings_page,
            "converter": self.converter_page,
            "tutorial": self.tutorial_page,
        }

        page = page_map.get(target)

        if page is None:
            return

        index = self.pages.indexOf(page)

        if index < 0:
            return

        self.sidebar.select_page(index)
        self.pages.setCurrentIndex(index)

    def _change_page(
        self,
        index: int,
    ) -> None:
        self.pages.setCurrentIndex(index)
        page = self.pages.widget(index)

        if page is self.home_page:
            self._refresh_home_page()
        elif page is self.recent_page:
            self._refresh_recent_page()
        elif page is self.favorites_page:
            self._refresh_favorites_page()
        elif page is self.archive_page:
            self._refresh_archive_page()
        elif page is self.settings_page:
            self._refresh_audit_page()

    def _refresh_home_page(self) -> None:
        if not hasattr(
            self,
            "home_page",
        ):
            return

        active_template_ids = {
            package.template_id
            for package in self.templates
        }

        favorite_count = sum(
            1
            for template_id
            in self.favorite_store.favorite_ids()
            if template_id in active_template_ids
        )

        recent_documents = (
            self.local_store.list_recent()
        )
        profiles = (
            self.local_store.list_profiles()
        )

        self.home_page.update_overview(
            template_count=len(self.templates),
            favorite_count=favorite_count,
            recent_count=len(recent_documents),
            profile_count=len(profiles),
            recent_documents=recent_documents,
        )

    def _open_output_folder(self) -> None:
        folder = self._output_root()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    def _show_placeholder_guide(self) -> None:
        self._show_tutorial_page()
        self.tutorial_page.show_markers_tab()

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            'Sobre o Padroniza',
            "Padroniza\n\n"
            "Geração de DOCX com validação de campos, perfis, rascunhos, documentos recentes, "
            "pacotes em lote, importação e exportação de modelos, histórico de versões, diagnósticos, "
            "conversão integrada de DOCX/PDF, numeração, backups e histórico de auditoria. Nenhum "
            "aplicativo externo de escritório é necessário para a conversão.",
        )
