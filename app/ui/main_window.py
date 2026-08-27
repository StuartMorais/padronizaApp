from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from app.repositories.favorites import FavoriteStore
from app.repositories.local_data import LocalDataStore
from app.repositories.templates import TemplateRepository
from app.core.settings import APPLICATION, ORGANIZATION
from app.services.generation import GenerationService
from app.services.output_planner import OutputPlanner
from app.services.templates import TemplatePackage
from app.ui.theme import ThemeManager
from app.ui.mixins.backup import BackupActionsMixin
from app.ui.mixins.generation import GenerationActionsMixin
from app.ui.mixins.navigation import NavigationMixin
from app.ui.mixins.profiles import ProfileDraftMixin
from app.ui.mixins.recent import RecentArchiveMixin
from app.ui.mixins.settings import SettingsMixin
from app.ui.mixins.templates import TemplateActionsMixin
from app.ui.template_manager.template_manager_dialog import TemplateManagerDialog
from app.ui.widgets.context_help import HelpIconButton, HelpLabel
from app.ui.widgets.document_form import DocumentForm
from app.ui.widgets.empty_state import EmptyState
from app.ui.widgets.file_converter_page import FileConverterPage
from app.ui.widgets.home_page import HomePage
from app.ui.widgets.sidebar import Sidebar
from app.ui.widgets.template_header import TemplateHeader
from app.ui.widgets.tutorial_page import TutorialPage


class MainWindow(
    SettingsMixin,
    TemplateActionsMixin,
    ProfileDraftMixin,
    GenerationActionsMixin,
    RecentArchiveMixin,
    BackupActionsMixin,
    NavigationMixin,
    QMainWindow,
):
    def __init__(
        self,
        project_root: Path,
        theme_manager: ThemeManager,
        *,
        default_output_dir: Path | None = None,
        managed_storage: bool = False,
    ) -> None:
        super().__init__()
        self.project_root = Path(project_root)
        self.theme_manager = theme_manager
        self.managed_storage = bool(managed_storage)
        self.templates_dir = self.project_root / "templates"
        self.data_dir = self.project_root / "data"
        self.default_output_dir = Path(
            default_output_dir or (self.project_root / "output")
        )
        self.settings = QSettings(ORGANIZATION, APPLICATION)
        self.favorite_store = FavoriteStore(self.settings)
        self.local_store = LocalDataStore(self.data_dir)
        self.output_planner = OutputPlanner(self.local_store)
        self.generation_service = GenerationService(
            self.local_store,
            self.output_planner,
        )
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

        self.assisted_detection_banner = QFrame()
        self.assisted_detection_banner.setObjectName("assistedDetectionBanner")
        assisted_layout = QHBoxLayout(self.assisted_detection_banner)
        assisted_layout.setContentsMargins(14, 10, 12, 10)
        assisted_layout.setSpacing(10)

        assisted_text_layout = QVBoxLayout()
        assisted_text_layout.setSpacing(2)
        assisted_title = QLabel("Modelo criado com detecção assistida")
        assisted_title.setObjectName("assistedDetectionTitle")
        assisted_message = QLabel(
            "Alguns campos podem precisar de ajustes. Se algo parecer incorreto durante "
            "o preenchimento, você pode editar o modelo e continuar usando-o normalmente."
        )
        assisted_message.setObjectName("assistedDetectionText")
        assisted_message.setWordWrap(True)
        assisted_text_layout.addWidget(assisted_title)
        assisted_text_layout.addWidget(assisted_message)
        assisted_layout.addLayout(assisted_text_layout, 1)

        self.assisted_edit_button = QPushButton("Editar modelo")
        self.assisted_edit_button.setToolTip(
            "Abrir o modelo atual para corrigir campos, rótulos, opções ou organização."
        )
        self.assisted_edit_button.clicked.connect(self._edit_active_template)
        assisted_layout.addWidget(self.assisted_edit_button)
        self.assisted_detection_banner.hide()
        layout.addWidget(self.assisted_detection_banner)

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
                '<p><b>Aplicar perfil</b> restaura campos compatíveis pelo ID e pela '
                'chave de perfil. Para campos nativos ou detectados automaticamente, '
                'também compara de forma conservadora o rótulo, tipo e seção do campo. '
                'Correspondências ambíguas são ignoradas. Revise os dados antes de gerar.</p>'
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
        self.document_form.edit_field_requested.connect(
            self._edit_active_template_field
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # The model library is the single management hub.  It is the same
        # library UI that used to live in a separate modal dialog, embedded
        # directly in the main Modelos page.  Creation/editing still opens the
        # dedicated TemplateEditorDialog because those are focused authoring
        # tasks rather than library navigation.
        self.template_manager_panel = TemplateManagerDialog(
            self.templates_dir,
            self.favorite_store,
            page,
            embedded=True,
        )
        self.template_manager_panel.library_changed.connect(
            self._load_templates
        )
        self.template_manager_panel.template_use_requested.connect(
            self._use_template_from_library
        )
        layout.addWidget(self.template_manager_panel, 1)
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
                    'biblioteca. A exclusão permanente está disponível na página <b>Modelos</b>.</p>'
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
            'Ir para Modelos',
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

        portable = QGroupBox('Armazenamento do aplicativo')
        portable_layout = QVBoxLayout(portable)
        self.portable_checkbox = QCheckBox(
            'Armazenar as configurações junto à pasta de dados do projeto'
        )
        self.portable_checkbox.toggled.connect(self._save_preferences)
        portable_note = QLabel()
        portable_note.setObjectName("mutedText")
        portable_note.setWordWrap(True)
        portable_row = QHBoxLayout()
        portable_row.addWidget(self.portable_checkbox)
        portable_row.addWidget(
            HelpIconButton(
                'Armazenamento persistente',
                (
                    '<p>Na versão instalada ou portátil em arquivo único, modelos, '
                    'históricos, backups e configurações são mantidos em uma pasta '
                    'gravável do Windows.</p>'
                    '<p>Isso impede que os dados sejam perdidos quando o executável '
                    'temporário for fechado ou atualizado.</p>'
                ),
            )
        )
        portable_row.addStretch()
        portable_layout.addLayout(portable_row)

        if self.managed_storage:
            self.portable_checkbox.blockSignals(True)
            self.portable_checkbox.setChecked(True)
            self.portable_checkbox.blockSignals(False)
            self.portable_checkbox.setEnabled(False)
            portable_note.setText(
                'A versão compilada usa armazenamento persistente automaticamente. '
                f'Pasta de dados: {self.project_root}'
            )
        else:
            portable_note.setText(
                'A alteração será aplicada na próxima inicialização. '
                'Modelos, perfis, históricos e backups permanecem disponíveis '
                'nas pastas do projeto.'
            )

        open_data_folder_button = QPushButton('Abrir pasta de dados')
        open_data_folder_button.clicked.connect(self._open_data_folder)
        portable_layout.addWidget(portable_note)
        portable_layout.addWidget(open_data_folder_button, 0, Qt.AlignmentFlag.AlignLeft)
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








    # Templates ----------------------------------------------------------------








    # Favorites ----------------------------------------------------------------









    # Profiles/drafts -----------------------------------------------------------













    # Validation/preview/generation --------------------------------------------



    @staticmethod







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



    # Recent documents ----------------------------------------------------------










    # Archive/audit/backup ------------------------------------------------------
















    # Navigation/help -----------------------------------------------------------











