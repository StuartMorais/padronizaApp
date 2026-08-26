from __future__ import annotations

import json
from datetime import datetime
from copy import deepcopy
from pathlib import Path
from threading import Event
from typing import Any
from uuid import uuid4

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QFormLayout,
    QLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.dialogs.automatic_detection_dialog import AutomaticDetectionDialog
from app.ui.dialogs.diagnostics_dialog import DiagnosticsDialog
from app.ui.dialogs.error_dialog import show_exception_dialog
from app.ui.dialogs.filename_builder_dialog import FilenameBuilderDialog
from app.ui.dialogs.field_library_dialog import FieldLibraryDialog
from app.document.detection.application import apply_docx_field_candidates
from app.document.docx.generator import generate_docx
from app.document.docx.repair import repair_repeatable_table_markers
from app.document.docx.scanner import clear_docx_scan_cache
from app.document.detection.candidates import candidate_field_definitions
from app.document.detection.detector import detect_docx_with_report
from app.document.detection.models import AutomaticDetectionCancelled
from app.repositories.field_library import FieldLibraryStore
from app.core.atomic_output import publish_staged_output, staged_output
from app.core.json_io import atomic_write_json
from app.core.paths import resolve_application_paths
from app.domain.field_metadata import preserved_editor_field_metadata
from app.domain.template_quality import field_configuration_issues, issue_counts
from app.domain.validation import sample_values_for_fields
from app.domain.field_types import FIELD_TYPE_ORDER
from app.document.understanding.layout import layout_quality_issues, normalize_form_layout
from app.domain.section_card_model import (
    build_section_card_models,
    rename_section_fields,
    reorder_section_fields,
)
from app.document.understanding.smart_template import readiness_report, smart_fields_from_docx
from app.document.diagnostics import diagnose_template, diagnostics_text
from app.core.system_open import SystemOpenError, open_file
from app.document.source import (
    SUPPORTED_TEMPLATE_SUFFIXES,
    TemplateSourceError,
    prepare_template_source,
)
from app.repositories.templates import TemplateRepository
from app.ui.widgets.clickable_drop_zone import ClickableDropZone
from app.ui.widgets.context_help import HelpIconButton, HelpLabel
from app.ui.widgets.toast import show_toast
from app.ui.widgets.document_form import DocumentForm
from app.ui.widgets.field_layout_editor import FieldLayoutEditor
from app.ui.widgets.repeatable_table import FieldConfigurationEditor
from app.ui.widgets.template_section_card import TemplateSectionCard


class _TemplateFileDropZone(ClickableDropZone):
    SUPPORTED_SUFFIXES = SUPPORTED_TEMPLATE_SUFFIXES
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.setObjectName(
            "templateDocxDropZone"
        )
        self.setAcceptDrops(True)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.setMinimumHeight(132)
        self.setMaximumHeight(132)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        self.setToolTip(
            'Arraste um arquivo DOCX ou PDF para cá ou clique para selecioná-lo.'
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            16,
            13,
            16,
            13,
        )
        layout.setSpacing(5)
        layout.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.title_label = QLabel(
            'Arraste um arquivo de modelo para cá'
        )
        self.title_label.setObjectName(
            "templateDocxDropTitle"
        )
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.subtitle_label = QLabel(
            'DOCX ou PDF'
        )
        self.subtitle_label.setObjectName(
            "templateDocxDropText"
        )
        self.subtitle_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.subtitle_label.setWordWrap(True)

        self.browse_button = self.create_browse_button(
            "Selecionar arquivo"
        )

        self.add_drop_content(
            layout,
            self.title_label,
            self.subtitle_label,
            self.browse_button,
        )

    def set_selected_file(
        self,
        path: Path,
    ) -> None:
        self.setProperty(
            "selected",
            True,
        )
        self.title_label.setText(
            path.name
        )
        self.subtitle_label.setText(
            f'{path.suffix.upper().lstrip(".")} selecionado. Arraste outro arquivo para substituí-lo.'
        )
        self.browse_button.setText(
            'Substituir arquivo'
        )
        self.set_drag_active(False)



class _AutomaticDetectionWorker(QObject):
    """Run assisted DOCX detection off the GUI thread with cooperative cancel."""

    result_ready = Signal(object)
    failed = Signal(object)
    canceled = Signal()
    finished = Signal()

    def __init__(
        self,
        source: Path,
        existing_ids: set[str],
        existing_fields: list[dict[str, Any]],
    ) -> None:
        super().__init__()
        self.source = Path(source)
        self.existing_ids = set(existing_ids)
        self.existing_fields = [deepcopy(field) for field in existing_fields]
        self._cancel_event = Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            candidates, report = detect_docx_with_report(
                self.source,
                existing_field_ids=self.existing_ids,
                existing_fields=self.existing_fields,
                cancel_check=self._cancel_event.is_set,
            )
        except AutomaticDetectionCancelled:
            self.canceled.emit()
        except Exception as exc:
            self.failed.emit(exc)
        else:
            # Send all data needed by the GUI as one queued payload. Connecting
            # directly to a QObject method keeps UI work on the main thread; a
            # lambda connected to a worker-thread signal could otherwise run in
            # the emitter thread.
            self.result_ready.emit((candidates, deepcopy(self.existing_fields), report.as_dict()))
        finally:
            self.finished.emit()


# noinspection SpellCheckingInspection
class TemplateEditorDialog(QDialog):
    FIELD_TYPES = FIELD_TYPE_ORDER
    FIELD_TYPE_LABELS = {
        "text": "Texto",
        "multiline": "Texto com várias linhas",
        "date": "Data",
        "checkbox": "Caixa de seleção",
        "dropdown": "Lista suspensa",
        "currency": "Moeda",
        "integer": "Número inteiro",
        "decimal": "Número decimal",
        "percentage": "Porcentagem",
        "cnpj": "CNPJ",
        "cpf": "CPF",
        "cep": "CEP",
        "phone": "Telefone",
        "email": "E-mail",
        "repeatable_table": "Tabela repetível",
    }

    def __init__(
        self,
        repository: TemplateRepository,
        template_id: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.repository = repository
        self.template_id = template_id
        self.saved_template_id: str | None = template_id
        self.selected_docx: Path | None = None
        self.selected_input_file: Path | None = None
        self.selected_input_was_pdf = False
        self.docx_was_replaced = False
        self.data_dir = self.repository.templates_dir.parent / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.field_library = FieldLibraryStore(self.data_dir)
        draft_name = f"{template_id or 'new-template'}.json"
        self.editor_draft_path = self.data_dir / "template_editor_drafts" / draft_name
        self._history: list[dict[str, Any]] = []
        self._history_index = -1
        self._initial_snapshot: dict[str, Any] | None = None
        self._applying_snapshot = False
        self._dirty = False
        self._duplicate_matches: list[dict[str, Any]] = []
        self._similar_name_matches: list[dict[str, Any]] = []
        self._original_template_name = ""
        self._automatic_work_files: set[Path] = set()
        self._source_field_hints: list[dict[str, Any]] = []
        self._detection_thread: QThread | None = None
        self._detection_worker: _AutomaticDetectionWorker | None = None
        self._detection_progress: QProgressDialog | None = None

        self.change_timer = QTimer(self)
        self.change_timer.setSingleShot(True)
        self.change_timer.setInterval(450)
        self.change_timer.timeout.connect(self._commit_editor_change)

        self.setWindowTitle('Criar modelo' if template_id is None else 'Editar modelo')
        self.resize(1260, 820)
        self.setMinimumSize(760, 560)
        self.setSizeGripEnabled(True)

        self.name_input = QLineEdit()

        self.similar_name_warning_label = QLabel()
        self.similar_name_warning_label.setObjectName(
            "similarTemplateNameWarning"
        )
        self.similar_name_warning_label.setWordWrap(True)
        self.similar_name_warning_label.hide()

        self.category_input = QLineEdit()
        self.version_input = QLineEdit("1.0")
        self.description_input = QPlainTextEdit()
        self.description_input.setMinimumHeight(64)
        self.description_input.setMaximumHeight(84)
        self.docx_input = QLineEdit()
        self.docx_input.setReadOnly(True)

        self.duplicate_warning_label = QLabel()
        self.duplicate_warning_label.setObjectName(
            "duplicateTemplateWarning"
        )
        self.duplicate_warning_label.setWordWrap(True)
        self.duplicate_warning_label.hide()

        self.filename_input = QLineEdit("{{template.name}}.docx")
        self.folder_pattern_input = QLineEdit()
        self.folder_pattern_input.setPlaceholderText("Exemplo: {{year}}/{{process.number}}/{{company.legal_name}}")
        self.numbering_checkbox = QCheckBox('Ativar numeração sequencial para este modelo')
        self.numbering_key_input = QLineEdit()
        self.numbering_key_input.setPlaceholderText('Por padrão, usa o ID do modelo')
        self.numbering_padding_input = QSpinBox()
        self.numbering_padding_input.setRange(1, 10)
        self.numbering_padding_input.setValue(4)

        self.docx_drop_zone = (
            _TemplateFileDropZone()
        )
        self.browse_button = (
            self.docx_drop_zone.browse_button
        )
        self.docx_tools_button = QPushButton(
            'Ferramentas do arquivo'
        )
        self.docx_tools_menu = QMenu(self)

        self.scan_action = QAction(
            'Localizar campos',
            self,
        )
        self.scan_action.triggered.connect(
            self._scan_fields
        )
        self.docx_tools_menu.addAction(
            self.scan_action
        )

        self.automatic_detection_action = QAction(
            'Detectar campos sem tags...',
            self,
        )
        self.automatic_detection_action.setToolTip(
            'Sugere áreas preenchíveis em DOCX ou PDF e converte somente as aprovadas em campos do modelo.'
        )
        self.automatic_detection_action.triggered.connect(
            self._detect_fields_without_tags
        )
        self.docx_tools_menu.addAction(
            self.automatic_detection_action
        )

        self.diagnostics_action = QAction(
            'Executar diagnóstico',
            self,
        )
        self.diagnostics_action.triggered.connect(
            self._show_diagnostics
        )
        self.docx_tools_menu.addAction(
            self.diagnostics_action
        )

        self.docx_tools_button.setMenu(
            self.docx_tools_menu
        )

        self.filename_builder_button = QPushButton(
            'Montar nome do arquivo...'
        )

        self.fields_table = QTableWidget(0, 12)
        self.fields_table.setHorizontalHeaderLabels(
            [
                'ID do campo',
                'Rótulo',
                'Tipo',
                'Obrigatório',
                'Opções / colunas',
                'Seção',
                'Chave do perfil',
                'Grupo',
                'Escolha única',
                'Visível quando',
                'Layout',
                'Status',
            ]
        )
        self.fields_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.fields_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.fields_table.verticalHeader().setVisible(False)
        self.fields_table.setAlternatingRowColors(True)
        self.fields_table.setMinimumHeight(220)
        header = self.fields_table.horizontalHeader()
        for column in range(self.fields_table.columnCount()):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        widths = [210, 210, 150, 80, 245, 170, 170, 130, 100, 190, 250, 105]
        for column, width in enumerate(widths):
            self.fields_table.setColumnWidth(column, width)

        field_header_help = [
            'Identificador usado nos marcadores, como {{company.cnpj}}.',
            'Nome legível exibido no formulário. Quando possível, é identificado a partir do texto antes do marcador no DOCX.',
            'Define o controle e a validação do campo.',
            'Impede a geração enquanto o campo visível estiver vazio ou inválido.',
            'Abre o editor de opções da lista suspensa ou das colunas de uma tabela repetível.',
            'Grupo visual no formulário de geração.',
            'Chave usada para preencher o campo a partir de um perfil.',
            'Agrupa caixas de seleção relacionadas.',
            'Permite apenas uma caixa marcada dentro do mesmo grupo.',
            'Regra no formato campo.id=conteudo_esperado. Exemplo: declaracao.tipo=Integral.',
            'Define se o campo fica em grade, largura total, grupo de escolha ou tabela. Use Detalhes para configurar grupo, linha e coluna.',
            'Validação rápida do campo no editor. Passe o mouse para ver detalhes.',
        ]
        for column, help_text in enumerate(field_header_help):
            header_item = self.fields_table.horizontalHeaderItem(column)
            if header_item is not None:
                header_item.setToolTip(help_text)

        self.add_field_button = QPushButton('Adicionar campo')
        self.remove_field_button = QPushButton('Remover selecionado')
        self.move_up_button = QPushButton('Mover para cima')
        self.move_down_button = QPushButton('Mover para baixo')
        self.insert_group_button = QPushButton('Inserir grupo de campos')
        self.save_group_button = QPushButton('Salvar seleção como grupo')
        self.undo_button = QPushButton('Desfazer')
        self.redo_button = QPushButton('Refazer')
        self.revert_button = QPushButton('Reverter alterações')
        self.save_button = QPushButton('Salvar alterações' if template_id else 'Criar modelo')
        self.save_button.setObjectName("primaryButton")
        self.cancel_button = QPushButton('Cancelar')

        self.field_search_input = QLineEdit()
        self.field_search_input.setPlaceholderText('Filtrar por ID, rótulo ou seção…')
        self.field_search_input.setClearButtonEnabled(True)

        self.field_type_filter = QComboBox()
        self.field_type_filter.addItem('Todos os tipos', 'all')
        for field_type_key in self.FIELD_TYPES:
            self.field_type_filter.addItem(
                self.FIELD_TYPE_LABELS.get(field_type_key, field_type_key),
                field_type_key,
            )

        self.field_status_filter = QComboBox()
        self.field_status_filter.addItem('Todos os status', 'all')
        self.field_status_filter.addItem('Somente OK', 'ok')
        self.field_status_filter.addItem('Com erro', 'error')
        self.field_status_filter.addItem('Revisar', 'warning')

        self.field_validation_summary_label = QLabel()
        self.field_validation_summary_label.setObjectName('mutedText')
        self.field_validation_summary_label.setWordWrap(True)

        self.simple_fields_checkbox = QCheckBox('Modo simples')
        self.simple_fields_checkbox.setChecked(True)
        self.tag_guide_button = QPushButton('Abrir guia de tags')

        self.section_search_input = QLineEdit()
        self.section_search_input.setPlaceholderText('Pesquisar seção, campo ou identificador…')
        self.section_search_input.setClearButtonEnabled(True)

        self.section_cards_scroll = QScrollArea()
        self.section_cards_scroll.setObjectName('templateSectionCardsScroll')
        self.section_cards_scroll.setWidgetResizable(True)
        self.section_cards_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.section_cards_scroll.setMinimumHeight(300)

        self.section_cards_container = QWidget()
        self.section_cards_container.setObjectName('templateSectionCardsContainer')
        self.section_cards_layout = QVBoxLayout(self.section_cards_container)
        self.section_cards_layout.setContentsMargins(2, 2, 2, 2)
        self.section_cards_layout.setSpacing(9)
        self.section_cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.section_cards_scroll.setWidget(self.section_cards_container)
        self.section_cards: list[TemplateSectionCard] = []

        self.section_empty_label = QLabel(
            'Nenhuma seção corresponde à pesquisa. Limpe o filtro ou revise os campos na aba Campos.'
        )
        self.section_empty_label.setObjectName('templateSectionEmptyState')
        self.section_empty_label.setWordWrap(True)
        self.section_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.section_empty_label.hide()

        self.new_section_button = QPushButton('+ Nova seção')
        self.rename_section_button = QPushButton('Renomear seção…')
        self.assign_section_button = QPushButton('Atribuir campos selecionados…')
        self.expand_sections_button = QPushButton('Expandir todas')
        self.collapse_sections_button = QPushButton('Recolher todas')

        self.form_preview = DocumentForm()
        self.form_preview_scroll = QScrollArea()
        self.form_preview_scroll.setWidgetResizable(True)
        self.form_preview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.addWidget(self.form_preview)
        preview_layout.addStretch()
        self.form_preview_scroll.setWidget(preview_container)
        self.preview_sample_button = QPushButton('Preencher com exemplos')
        self.preview_clear_button = QPushButton('Limpar prévia')
        self.test_template_button = QPushButton('Gerar DOCX de teste…')

        self.docx_drop_zone.browse_requested.connect(
            self._choose_template_file
        )
        self.docx_drop_zone.file_dropped.connect(
            self._set_template_file
        )
        self.filename_builder_button.clicked.connect(
            self._build_filename
        )
        self.add_field_button.clicked.connect(self._add_empty_field)
        self.remove_field_button.clicked.connect(self._remove_selected_fields)
        self.move_up_button.clicked.connect(lambda: self._move_selected(-1))
        self.move_down_button.clicked.connect(lambda: self._move_selected(1))
        self.insert_group_button.clicked.connect(self._insert_field_group)
        self.save_group_button.clicked.connect(self._save_selected_field_group)
        self.undo_button.clicked.connect(self._undo_editor_change)
        self.redo_button.clicked.connect(self._redo_editor_change)
        self.revert_button.clicked.connect(self._revert_editor_changes)
        self.save_button.clicked.connect(self._save_template)
        self.cancel_button.clicked.connect(self._cancel_editor)
        self.field_search_input.textChanged.connect(self._filter_field_rows)
        self.field_type_filter.currentIndexChanged.connect(self._apply_field_filters)
        self.field_status_filter.currentIndexChanged.connect(self._apply_field_filters)
        self.simple_fields_checkbox.toggled.connect(self._set_simple_fields_mode)
        self.tag_guide_button.clicked.connect(self._open_tag_guide)
        self.new_section_button.clicked.connect(self._create_section)
        self.rename_section_button.clicked.connect(self._rename_section)
        self.assign_section_button.clicked.connect(self._assign_selected_to_section)
        self.section_search_input.textChanged.connect(self._filter_section_cards)
        self.expand_sections_button.clicked.connect(lambda: self._set_all_section_cards_expanded(True))
        self.collapse_sections_button.clicked.connect(lambda: self._set_all_section_cards_expanded(False))
        self.preview_sample_button.clicked.connect(self.form_preview.load_sample_data)
        self.preview_clear_button.clicked.connect(self.form_preview.clear_values)
        self.test_template_button.clicked.connect(self._generate_test_document)

        QShortcut(QKeySequence.StandardKey.Undo, self).activated.connect(self._undo_editor_change)
        QShortcut(QKeySequence.StandardKey.Redo, self).activated.connect(self._redo_editor_change)

        general_group = self._create_general_group()
        output_group = self._create_output_group()

        top_widget = QWidget()
        top_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        top_row = QHBoxLayout(top_widget)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(12)
        top_row.addWidget(general_group, 3)
        top_row.addWidget(output_group, 2)
        top_widget.setMinimumHeight(
            max(
                general_group.minimumSizeHint().height(),
                output_group.minimumSizeHint().height(),
            )
        )

        content_widget = QWidget()
        content_widget.setObjectName("templateEditorContent")
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)
        content_layout.setSizeConstraint(
            QLayout.SizeConstraint.SetMinimumSize
        )
        content_layout.addWidget(top_widget)
        content_layout.addWidget(self._create_readiness_group())
        content_layout.addWidget(self._create_fields_group(), 1)

        self.editor_scroll = QScrollArea()
        self.editor_scroll.setObjectName("templateEditorScroll")
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.editor_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.editor_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.editor_scroll.setWidget(content_widget)

        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(self.save_button)
        bottom.addWidget(self.cancel_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        layout.addWidget(self.editor_scroll, 1)
        layout.addLayout(bottom)

        if self.template_id is not None:
            self._applying_snapshot = True
            try:
                self._load_existing_template()
            finally:
                self._applying_snapshot = False
                self.change_timer.stop()
                self._dirty = False

        self._connect_change_tracking()
        self._initial_snapshot = self._snapshot_editor_state()
        self._history = [deepcopy(self._initial_snapshot)]
        self._history_index = 0
        self._recover_editor_draft()
        self._update_readiness()
        QTimer.singleShot(
            0,
            self._fit_to_available_screen,
        )

    def _fit_to_available_screen(self) -> None:
        screen = self.screen()
        if screen is None:
            return

        available = screen.availableGeometry()
        usable_width = max(
            480,
            available.width() - 24,
        )
        usable_height = max(
            420,
            available.height() - 24,
        )

        minimum_width = max(
            480,
            min(
                900,
                available.width() - 100,
            ),
        )
        minimum_height = max(
            420,
            min(
                620,
                available.height() - 100,
            ),
        )
        self.setMinimumSize(
            minimum_width,
            minimum_height,
        )

        self.resize(
            max(
                minimum_width,
                min(1320, usable_width),
            ),
            max(
                minimum_height,
                min(900, usable_height),
            ),
        )

    @staticmethod
    def _create_form_group(
        title: str,
    ) -> tuple[QGroupBox, QFormLayout]:
        form_group = QGroupBox(title)
        form_group.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum,
        )
        form = QFormLayout(form_group)
        form.setContentsMargins(14, 16, 14, 14)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(9)
        return form_group, form

    def _create_general_group(self) -> QGroupBox:
        form_group, form = self._create_form_group(
            'Informações do modelo'
        )

        name_widget = QWidget()
        name_layout = QVBoxLayout(name_widget)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(5)
        name_layout.addWidget(self.name_input)
        name_layout.addWidget(
            self.similar_name_warning_label
        )

        form.addRow(
            HelpLabel(
                'Nome do modelo:',
                'Nome do modelo',
                (
                    '<p>Use um nome curto e fácil de reconhecer na biblioteca.</p>'
                    '<p>O Padroniza compara o nome com os modelos existentes e '
                    'avisa quando encontra nomes muito semelhantes.</p>'
                ),
            ),
            name_widget,
        )
        form.addRow(
            HelpLabel(
                'Categoria:',
                'Categoria do modelo',
                (
                    '<p>Use uma categoria curta para organizar e localizar modelos, '
                    'como <b>Compras</b>, <b>Contratos</b> ou <b>Declarações</b>.</p>'
                ),
            ),
            self.category_input,
        )
        form.addRow(
            HelpLabel(
                'Versão:',
                'Versão do modelo',
                (
                    '<p>É uma identificação informativa, como <b>1.0</b> ou <b>2.1</b>.</p>'
                    '<p>O histórico de versões guarda cópias anteriores quando o modelo '
                    'é atualizado.</p>'
                ),
            ),
            self.version_input,
        )
        form.addRow(
            HelpLabel(
                'Descrição:',
                'Descrição do modelo',
                (
                    '<p>Explique quando o modelo deve ser usado e qual documento ele gera.</p>'
                    '<p>A descrição ajuda outros usuários a escolher o modelo correto.</p>'
                ),
            ),
            self.description_input,
        )

        docx_widget = QWidget()
        docx_layout = QVBoxLayout(
            docx_widget
        )
        docx_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )
        docx_layout.setSpacing(7)
        docx_layout.addWidget(
            self.docx_drop_zone
        )

        selected_row = QHBoxLayout()
        selected_row.setSpacing(6)
        selected_row.addWidget(
            self.docx_input,
            1,
        )
        selected_row.addWidget(
            self.docx_tools_button
        )
        docx_layout.addLayout(
            selected_row
        )
        docx_layout.addWidget(
            self.duplicate_warning_label
        )

        form.addRow(
            HelpLabel(
                'Arquivo do modelo:',
                'Documento DOCX ou PDF de origem',
                (
                    '<p>Selecione um DOCX ou PDF. O arquivo contém o texto e a estrutura '
                    'que serão preenchidos durante a geração.</p>'
                    '<p>Exemplo de marcador: <b>{{company.legal_name}}</b>.</p>'
                    '<p>PDFs são reconstruídos internamente como DOCX antes da análise. '
                    'A aparência pode ser simplificada em PDFs complexos.</p>'
                    '<p>O Padroniza também avisa quando o mesmo conteúdo do modelo já '
                    'está sendo usado por outro modelo.</p>'
                ),
            ),
            docx_widget,
        )
        return form_group

    def _create_readiness_group(self) -> QGroupBox:
        group = QGroupBox('Verificação do modelo')
        layout = QHBoxLayout(group)
        layout.setContentsMargins(12, 12, 12, 12)

        self.readiness_label = QLabel('Verificando o modelo…')
        self.readiness_label.setObjectName("templateReadinessTitle")
        self.readiness_details = QLabel()
        self.readiness_details.setObjectName("mutedText")
        self.readiness_details.setWordWrap(True)

        text_layout = QVBoxLayout()
        text_layout.addWidget(self.readiness_label)
        text_layout.addWidget(self.readiness_details)

        self.safe_fix_button = QPushButton('Aplicar correções seguras')
        self.safe_fix_button.clicked.connect(self._apply_safe_fixes)

        layout.addLayout(text_layout, 1)
        layout.addWidget(
            HelpIconButton(
                'Verificação e correções seguras',
                (
                    '<p>A verificação resume problemas que podem impedir ou prejudicar '
                    'a geração, como arquivo ausente, campos inválidos ou marcadores sem configuração.</p>'
                    '<p><b>Aplicar correções seguras</b> cria ou ajusta somente itens que '
                    'podem ser corrigidos sem apagar conteúdo manual.</p>'
                ),
            )
        )
        layout.addWidget(self.safe_fix_button)
        return group

    def _create_fields_group(self) -> QGroupBox:
        group = QGroupBox('Campos e seções')

        help_text = HelpLabel(
            'Configuração dos campos',
            'Campos, seções e regras',
            (
                '<p><b>Campos</b> define o tipo, o rótulo e a validação.</p>'
                '<p><b>Seções e layout</b> organiza o formulário em cartões de seção. '
                'Use o layout <b>Grupo de escolha</b> para alternativas exclusivas exibidas como '
                'caixas grandes e clicáveis, e <b>Tabela</b> para responsáveis organizados '
                'por linha e coluna.</p>'
                '<p><b>Prévia do formulário</b> permite revisar a organização antes de salvar.</p>'
                '<p>Em <b>Visível quando</b>, use '
                '<b>campo.id=conteudo_esperado</b>. Exemplo: '
                '<b>declaracao.tipo=Integral</b>.</p>'
            ),
        )
        help_text.label.setObjectName("mutedText")

        filter_row = QHBoxLayout()
        filter_row.setSpacing(7)
        filter_row.addWidget(self.field_search_input, 1)
        filter_row.addWidget(self.field_type_filter)
        filter_row.addWidget(self.field_status_filter)
        filter_row.addWidget(self.simple_fields_checkbox)
        filter_row.addWidget(self.tag_guide_button)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        buttons.addWidget(self.add_field_button)
        buttons.addWidget(self.remove_field_button)
        buttons.addWidget(self.move_up_button)
        buttons.addWidget(self.move_down_button)
        buttons.addWidget(self.insert_group_button)
        buttons.addWidget(self.save_group_button)
        buttons.addStretch()
        buttons.addWidget(self.undo_button)
        buttons.addWidget(self.redo_button)
        buttons.addWidget(self.revert_button)

        fields_tab = QWidget()
        fields_layout = QVBoxLayout(fields_tab)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.setSpacing(7)
        fields_layout.addLayout(filter_row)
        fields_layout.addWidget(self.field_validation_summary_label)
        fields_layout.addLayout(buttons)
        fields_layout.addWidget(self.fields_table, 1)

        sections_tab = QWidget()
        sections_layout = QVBoxLayout(sections_tab)
        sections_layout.setContentsMargins(8, 8, 8, 8)
        sections_layout.setSpacing(9)
        section_hint = QLabel(
            'Cada cartão representa uma seção do formulário. Use as setas no cartão para '
            'mover a seção, o lápis para renomeá-la e “Editar” para abrir um campo na aba Campos.'
        )
        section_hint.setWordWrap(True)
        section_hint.setObjectName('mutedText')
        sections_layout.addWidget(section_hint)

        section_toolbar = QHBoxLayout()
        section_toolbar.setSpacing(6)
        section_toolbar.addWidget(self.new_section_button)
        section_toolbar.addWidget(self.rename_section_button)
        section_toolbar.addWidget(self.assign_section_button)
        section_toolbar.addStretch()
        section_toolbar.addWidget(self.expand_sections_button)
        section_toolbar.addWidget(self.collapse_sections_button)
        sections_layout.addLayout(section_toolbar)
        sections_layout.addWidget(self.section_search_input)
        sections_layout.addWidget(self.section_cards_scroll, 1)
        sections_layout.addWidget(self.section_empty_label)

        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_hint = QLabel(
            'Prévia interativa para revisar a organização. Os valores digitados aqui não são salvos.'
        )
        preview_hint.setObjectName('mutedText')
        preview_hint.setWordWrap(True)
        preview_layout.addWidget(preview_hint)
        preview_tools = QHBoxLayout()
        preview_tools.addWidget(self.preview_sample_button)
        preview_tools.addWidget(self.preview_clear_button)
        preview_tools.addStretch()
        preview_tools.addWidget(self.test_template_button)
        preview_layout.addLayout(preview_tools)
        preview_layout.addWidget(self.form_preview_scroll, 1)

        self.fields_tabs = QTabWidget()
        self.fields_tabs.addTab(fields_tab, 'Campos')
        self.fields_tabs.addTab(sections_tab, 'Seções e layout')
        self.fields_tabs.addTab(preview_tab, 'Prévia do formulário')
        self.fields_tabs.currentChanged.connect(self._fields_tab_changed)

        layout = QVBoxLayout(group)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(help_text)
        layout.addWidget(self.fields_tabs, 1)
        self._set_simple_fields_mode(True)
        return group

    def _set_simple_fields_mode(self, enabled: bool) -> None:
        # Essential columns stay visible; advanced automation rules are one click away.
        for column in (6, 7, 8, 9):
            self.fields_table.setColumnHidden(column, bool(enabled))
        self.fields_table.setColumnHidden(10, False)
        self.fields_table.setColumnHidden(11, False)
        widths = (
            [175, 185, 145, 82, 220, 150, 170, 130, 100, 190, 210, 100]
            if enabled
            else [210, 210, 150, 80, 245, 170, 170, 130, 100, 190, 250, 105]
        )
        for column, width in enumerate(widths):
            self.fields_table.setColumnWidth(column, width)

    def _filter_field_rows(self, _text: str = "") -> None:
        self._apply_field_filters()

    def _apply_field_filters(self, *_args) -> None:
        query = self.field_search_input.text().strip().casefold()
        type_filter = str(self.field_type_filter.currentData() or "all")
        status_filter = str(self.field_status_filter.currentData() or "all")

        for row in range(self.fields_table.rowCount()):
            haystack = " ".join(
                (self.fields_table.item(row, column).text() if self.fields_table.item(row, column) else "")
                for column in (0, 1, 5)
            ).casefold()
            type_combo = self.fields_table.cellWidget(row, 2)
            row_type = str(type_combo.currentData() or "text") if isinstance(type_combo, QComboBox) else "text"
            status_item = self.fields_table.item(row, 11)
            row_status = str(status_item.data(Qt.ItemDataRole.UserRole) or "ok") if status_item else "ok"
            visible = (
                (not query or query in haystack)
                and (type_filter == "all" or row_type == type_filter)
                and (status_filter == "all" or row_status == status_filter)
            )
            self.fields_table.setRowHidden(row, not visible)

    def _field_row_validation_snapshot(self, row: int) -> dict[str, Any]:
        """Project one editor row into the fast, source-independent validator.

        Unlike ``_collect_fields(validate=False)``, this deliberately keeps
        completely blank rows. That makes a newly-added unfinished field show
        an immediate status instead of shifting issue row numbers or silently
        appearing valid.
        """
        id_item = self.fields_table.item(row, 0)
        label_item = self.fields_table.item(row, 1)
        type_combo = self.fields_table.cellWidget(row, 2)
        configuration = self.fields_table.cellWidget(row, 4)
        visible_item = self.fields_table.item(row, 9)

        original = (
            id_item.data(Qt.ItemDataRole.UserRole)
            if id_item is not None
            else {}
        )
        original = deepcopy(original) if isinstance(original, dict) else {}
        field = preserved_editor_field_metadata(original)
        field_type = (
            str(type_combo.currentData() or "text")
            if isinstance(type_combo, QComboBox)
            else "text"
        )
        field.update(
            {
                "id": id_item.text().strip() if id_item else "",
                "label": label_item.text().strip() if label_item else "",
                "type": field_type,
            }
        )

        if isinstance(configuration, FieldConfigurationEditor):
            if field_type == "dropdown":
                field["options"] = configuration.options()
            elif field_type == "repeatable_table":
                field["columns"] = configuration.columns()

        raw_visible = visible_item.text().strip() if visible_item else ""
        if raw_visible:
            field["visible_when"] = (
                self._parse_visible_when(raw_visible) or raw_visible
            )
        return field

    def _refresh_field_validation(self) -> None:
        if not hasattr(self, "field_validation_summary_label"):
            return
        fields = [
            self._field_row_validation_snapshot(row)
            for row in range(self.fields_table.rowCount())
        ]
        issues = field_configuration_issues(fields)
        by_row: dict[int, list[Any]] = {}
        for issue in issues:
            by_row.setdefault(issue.row, []).append(issue)

        previous_signals = self.fields_table.blockSignals(True)
        try:
            for row in range(self.fields_table.rowCount()):
                status_item = self.fields_table.item(row, 11)
                if status_item is None:
                    status_item = QTableWidgetItem()
                    status_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    self.fields_table.setItem(row, 11, status_item)
                row_issues = by_row.get(row, [])
                errors = [issue for issue in row_issues if issue.severity == "error"]
                warnings = [issue for issue in row_issues if issue.severity == "warning"]
                if errors:
                    status = "error"
                    label = f"Erro ({len(errors)})"
                elif warnings:
                    status = "warning"
                    label = f"Revisar ({len(warnings)})"
                else:
                    status = "ok"
                    label = "OK"
                status_item.setText(label)
                status_item.setData(Qt.ItemDataRole.UserRole, status)
                status_item.setToolTip("\n".join(issue.message for issue in row_issues))

                id_item = self.fields_table.item(row, 0)
                if id_item is not None:
                    status_tip = "\n".join(issue.message for issue in row_issues)
                    id_item.setToolTip(status_tip)
        finally:
            self.fields_table.blockSignals(previous_signals)

        counts = issue_counts(issues)
        if not fields:
            text = "Nenhum campo configurado ainda."
        elif not issues:
            text = f"✓ {len(fields)} campo(s) sem problemas na validação rápida."
        else:
            text = (
                f"Validação rápida: {counts['error']} erro(s) e {counts['warning']} item(ns) para revisar "
                f"em {len(fields)} campo(s). Use o filtro de status para localizar os problemas."
            )
        self.field_validation_summary_label.setText(text)
        self._apply_field_filters()

    def _fields_tab_changed(self, index: int) -> None:
        if index == 1:
            self._refresh_section_tree()
        elif index == 2:
            self._refresh_form_preview()

    def _refresh_section_tree(self) -> None:
        # Kept under the original method name to preserve existing call sites.
        if not hasattr(self, "section_cards_layout"):
            return

        fields = self._collect_fields(validate=False)
        models = build_section_card_models(fields)

        while self.section_cards_layout.count():
            item = self.section_cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self.section_cards = []
        for index, model in enumerate(models):
            card = TemplateSectionCard(
                model,
                type_labels=self.FIELD_TYPE_LABELS,
                can_move_up=index > 0,
                can_move_down=index < len(models) - 1,
                parent=self.section_cards_container,
            )
            card.rename_requested.connect(self._rename_section_by_name)
            card.move_requested.connect(self._move_section)
            card.edit_field_requested.connect(self._edit_field_from_card)
            self.section_cards_layout.addWidget(card)
            self.section_cards.append(card)

        self._filter_section_cards(self.section_search_input.text())

    def _filter_section_cards(self, text: str) -> None:
        if not hasattr(self, "section_cards"):
            return
        query = str(text).strip().casefold()
        visible_count = 0
        for card in self.section_cards:
            visible = card.matches(query)
            card.setVisible(visible)
            visible_count += int(visible)
        if not self.section_cards:
            self.section_empty_label.setText(
                'Nenhuma seção disponível. Localize ou adicione campos na aba Campos.'
            )
            self.section_empty_label.show()
        else:
            self.section_empty_label.setText(
                'Nenhuma seção corresponde à pesquisa. Limpe o filtro ou revise os campos na aba Campos.'
            )
            self.section_empty_label.setVisible(visible_count == 0)

    def _set_all_section_cards_expanded(self, expanded: bool) -> None:
        for card in self.section_cards:
            if card.isVisible():
                card.set_expanded(expanded)

    def _edit_field_from_card(self, field_id: str) -> None:
        """Reveal and select exactly one field in the Campos editor.

        This method is used both by the section cards and by the inline
        ``Corrigir`` action in the generation form.  The latter opens this
        dialog before it is visible, so the actual focus is also reinforced
        on the next event-loop turn after the dialog geometry exists.
        """

        target = str(field_id).strip()
        if not target:
            return

        # A stale filter must never hide the field the user explicitly asked
        # to correct.  Clearing it also makes neighbouring context available
        # when they need to compare similar fields.
        if self.field_search_input.text():
            self.field_search_input.clear()
        self.fields_tabs.setCurrentIndex(0)

        for row in range(self.fields_table.rowCount()):
            id_item = self.fields_table.item(row, 0)
            if id_item is None or id_item.text().strip() != target:
                continue

            label_item = self.fields_table.item(row, 1)
            focus_column = 1 if label_item is not None else 0

            self.fields_table.clearSelection()
            self.fields_table.selectRow(row)
            self.fields_table.setCurrentCell(row, focus_column)
            self.fields_table.scrollToItem(
                id_item,
                QAbstractItemView.ScrollHint.PositionAtCenter,
            )
            self.fields_table.setFocus(Qt.FocusReason.OtherFocusReason)

            # The table lives inside the editor's outer scroll area.  Merely
            # scrolling the QTableWidget was not enough: the dialog could open
            # at its top and leave the selected row completely off-screen.
            # Reveal both levels now and once more after Qt has laid out the
            # newly shown modal dialog.
            self._reveal_field_editor_row(row)
            QTimer.singleShot(
                0,
                lambda selected_row=row: self._reveal_field_editor_row(selected_row),
            )
            return

    def _reveal_field_editor_row(self, row: int) -> None:
        if row < 0 or row >= self.fields_table.rowCount():
            return
        id_item = self.fields_table.item(row, 0)
        if id_item is None:
            return
        self.fields_tabs.setCurrentIndex(0)
        self.editor_scroll.ensureWidgetVisible(self.fields_tabs, 24, 70)
        self.fields_table.scrollToItem(
            id_item,
            QAbstractItemView.ScrollHint.PositionAtCenter,
        )

    def focus_field(self, field_id: str) -> None:
        """Deep-link ``Corrigir`` to the exact field row after the dialog opens."""

        target = str(field_id).strip()
        if not target:
            return
        # ``MainWindow`` calls focus_field() immediately before dialog.exec().
        # Deferring the operation guarantees that the outer scroll area already
        # has a real viewport/geometry, so the clicked field is actually visible
        # instead of only being selected somewhere below the fold.
        QTimer.singleShot(0, lambda key=target: self._edit_field_from_card(key))

    def _move_section(self, section_name: str, direction: int) -> None:
        fields = self._collect_fields(validate=False)
        reordered = reorder_section_fields(fields, section_name, direction)
        if reordered == fields:
            return
        self._load_fields_into_table(reordered)
        self._schedule_editor_change()
        self._refresh_section_tree()

    def _refresh_form_preview(self) -> None:
        if not hasattr(self, "form_preview"):
            return
        fields = self._collect_fields(validate=False)
        sections = self._build_sections(fields)
        self.form_preview.set_template(fields, sections)

    def _generate_test_document(self) -> None:
        """Generate a disposable/sample-filled DOCX from the current editor state."""

        if self.selected_docx is None:
            QMessageBox.warning(
                self,
                'Arquivo ausente',
                'Selecione um arquivo DOCX ou PDF antes de gerar um teste.',
            )
            return

        fields = self._collect_fields(validate=False)
        sections = self._build_sections(fields)
        try:
            report = diagnose_template(
                {
                    'fields': fields,
                    'sections': sections,
                    'output': {'filename_pattern': self.filename_input.text()},
                },
                self.selected_docx,
            )
        except Exception as exc:
            show_exception_dialog(
                self,
                'Não foi possível validar o modelo',
                'A validação do modelo falhou antes da geração de teste.',
                exc,
                stage='template_editor.test_document.preflight',
                context={'source': self.selected_docx or ''},
            )
            return

        if report.get('blocking'):
            DiagnosticsDialog(
                'Corrija o modelo antes do teste',
                diagnostics_text(report),
                self,
                report=report,
                on_field_activated=self.focus_field,
            ).exec()
            return

        default_dir = self.repository.templates_dir.parent / 'output'
        default_dir.mkdir(parents=True, exist_ok=True)
        base_name = ''.join(
            character if character.isalnum() or character in {' ', '-', '_'} else '-'
            for character in (self.name_input.text().strip() or 'modelo')
        ).strip(' .-_') or 'modelo'
        destination_value, _selected_filter = QFileDialog.getSaveFileName(
            self,
            'Gerar DOCX de teste',
            str(default_dir / f'{base_name}-teste.docx'),
            'Documento Word (*.docx)',
        )
        if not destination_value:
            return
        destination = Path(destination_value)
        if destination.suffix.lower() != '.docx':
            destination = destination.with_suffix('.docx')
        try:
            if destination.resolve() == self.selected_docx.resolve():
                QMessageBox.warning(
                    self,
                    'Destino inválido',
                    'O arquivo de teste não pode substituir o DOCX usado como modelo.',
                )
                return
        except OSError:
            pass

        try:
            effective_fields = smart_fields_from_docx(self.selected_docx, fields)
            sample_values = sample_values_for_fields(effective_fields)
            with staged_output(destination, suffix='.docx') as staged:
                generate_docx(self.selected_docx, staged, sample_values)
                publish_staged_output(staged, destination)
        except Exception as exc:
            show_exception_dialog(
                self,
                'Não foi possível gerar o DOCX de teste',
                'O teste encontrou um problema ao preencher o modelo com dados de exemplo.',
                exc,
                stage='template_editor.test_document.generate',
                context={'source': self.selected_docx or '', 'destination': destination},
            )
            return

        try:
            open_file(destination)
            detail = 'O documento foi gerado com valores de exemplo e aberto para revisão.'
        except SystemOpenError:
            detail = f'O documento foi gerado com valores de exemplo em {destination}.'
        show_toast(
            self,
            'DOCX de teste gerado',
            detail,
            duration=6500,
        )

    def _selected_field_rows(self) -> list[int]:
        rows = sorted(index.row() for index in self.fields_table.selectionModel().selectedRows())
        if not rows and self.fields_table.currentRow() >= 0:
            rows = [self.fields_table.currentRow()]
        return rows

    def _create_section(self) -> None:
        name, accepted = QInputDialog.getText(self, "Nova seção", "Nome da seção:")
        if not accepted or not name.strip():
            return
        rows = self._selected_field_rows()
        if rows:
            for row in rows:
                item = self.fields_table.item(row, 5)
                if item is None:
                    item = QTableWidgetItem()
                    self.fields_table.setItem(row, 5, item)
                item.setText(name.strip())
        self._schedule_editor_change()
        self._refresh_section_tree()
        if not rows:
            show_toast(
                self,
                "Seção criada",
                "Selecione campos na aba Campos e use “Atribuir seleção à seção”.",
                kind="info",
            )

    def _rename_section(self) -> None:
        fields = self._collect_fields(validate=False)
        sections = [model["title"] for model in build_section_card_models(fields)]
        if not sections:
            QMessageBox.warning(self, "Sem seções", "Adicione ou localize campos antes de renomear uma seção.")
            return
        old_name, accepted = QInputDialog.getItem(
            self, "Renomear seção", "Seção:", sections, 0, False
        )
        if not accepted or not str(old_name).strip():
            return
        self._rename_section_by_name(str(old_name))

    def _rename_section_by_name(self, old_name: str) -> None:
        new_name, accepted = QInputDialog.getText(
            self, "Renomear seção", "Novo nome:", text=str(old_name)
        )
        if not accepted or not new_name.strip() or new_name.strip() == str(old_name).strip():
            return
        fields = self._collect_fields(validate=False)
        try:
            renamed = rename_section_fields(fields, str(old_name), new_name)
        except ValueError as exc:
            QMessageBox.warning(self, "Nome inválido", str(exc))
            return
        self._load_fields_into_table(renamed)
        self._schedule_editor_change()
        self._refresh_section_tree()

    def _assign_selected_to_section(self) -> None:
        rows = self._selected_field_rows()
        if not rows:
            QMessageBox.warning(
                self,
                "Selecionar campos",
                "Selecione um ou mais campos na aba Campos antes de atribuí-los a uma seção.",
            )
            return
        fields = self._collect_fields(validate=False)
        available = [model["title"] for model in build_section_card_models(fields)]
        if available:
            name, accepted = QInputDialog.getItem(
                self, "Atribuir seção", "Seção:", available, 0, True
            )
        else:
            name, accepted = QInputDialog.getText(self, "Atribuir seção", "Seção:")
        if not accepted or not str(name).strip():
            return
        for row in rows:
            item = self.fields_table.item(row, 5)
            if item is None:
                item = QTableWidgetItem()
                self.fields_table.setItem(row, 5, item)
            item.setText(str(name).strip())
        self._schedule_editor_change()
        self._refresh_section_tree()

    def _open_tag_guide(self) -> None:
        guide_path = resolve_application_paths().resource_root / "docs" / "GUIA_DE_TAGS_PADRONIZA.docx"
        try:
            open_file(guide_path)
        except SystemOpenError as exc:
            QMessageBox.warning(self, "Guia de tags indisponível", str(exc))

    def _create_output_group(self) -> QGroupBox:
        form_group, form = self._create_form_group(
            'Saída e numeração'
        )

        filename_widget = QWidget()
        filename_row = QHBoxLayout(filename_widget)
        filename_row.setContentsMargins(0, 0, 0, 0)
        filename_row.setSpacing(6)
        filename_row.addWidget(self.filename_input, 1)
        filename_row.addWidget(self.filename_builder_button)

        form.addRow(
            HelpLabel(
                'Padrão do nome do arquivo:',
                'Nome automático do arquivo',
                (
                    '<p>Monte o nome final usando texto e marcadores.</p>'
                    '<p>Exemplo: <b>{{process.number}} - {{company.legal_name}}.docx</b>.</p>'
                    '<p>O botão <b>Montar nome do arquivo</b> ajuda a inserir '
                    'marcadores sem digitá-los manualmente.</p>'
                ),
            ),
            filename_widget,
        )
        form.addRow(
            HelpLabel(
                'Padrão de pastas:',
                'Organização automática em pastas',
                (
                    '<p>Cria subpastas dentro da pasta de saída configurada.</p>'
                    '<p>Exemplo: <b>{{year}}/{{process.number}}</b>.</p>'
                    '<p>Deixe em branco para salvar diretamente na pasta raiz de saída.</p>'
                ),
            ),
            self.folder_pattern_input,
        )

        numbering_widget = QWidget()
        numbering_layout = QHBoxLayout(numbering_widget)
        numbering_layout.setContentsMargins(0, 0, 0, 0)
        numbering_layout.setSpacing(6)
        numbering_layout.addWidget(self.numbering_checkbox)
        numbering_layout.addWidget(
            HelpIconButton(
                'Numeração sequencial',
                (
                    '<p>Adiciona um contador crescente que pode ser usado pelo '
                    'marcador <b>{{sequence}}</b>.</p>'
                    '<p>A chave separa contadores de modelos ou fluxos diferentes. '
                    'A quantidade de dígitos controla o preenchimento com zeros, '
                    'como <b>0001</b>.</p>'
                ),
            )
        )
        numbering_layout.addStretch()
        form.addRow("", numbering_widget)
        form.addRow(
            HelpLabel(
                'Chave da sequência:',
                'Chave da sequência',
                (
                    '<p>Separa contadores diferentes. Modelos com a mesma chave '
                    'compartilham a mesma sequência.</p>'
                    '<p>Use uma chave estável, como <b>declaracoes</b> ou <b>contratos</b>.</p>'
                ),
            ),
            self.numbering_key_input,
        )
        form.addRow(
            HelpLabel(
                'Dígitos da sequência:',
                'Quantidade de dígitos',
                (
                    '<p>Controla o preenchimento com zeros do marcador '
                    '<b>{{sequence}}</b>.</p>'
                    '<p>Com 4 dígitos, os primeiros valores serão 0001, 0002 e 0003.</p>'
                ),
            ),
            self.numbering_padding_input,
        )

        tokens = QLabel(
            "Os marcadores disponíveis incluem {{template.name}}, {{year}}, {{sequence}} e qualquer ID de campo, "
            "como {{process.number}}. Os padrões de pasta criam subpastas dentro da pasta raiz de saída configurada."
        )
        tokens.setWordWrap(True)
        tokens.setObjectName("mutedText")
        form.addRow("", tokens)
        return form_group

    def _load_existing_template(self) -> None:
        if self.template_id is None:
            return
        try:
            config = self.repository.read_config(self.template_id)
            template = config.get("template", {})
            output = config.get("output", {})
            numbering = config.get("numbering", {})

            self.name_input.setText(str(template.get("name", "")))
            self._original_template_name = self.name_input.text().strip()
            self.category_input.setText(str(template.get("category", "")))
            self.version_input.setText(str(template.get("version", "1.0")))
            self.description_input.setPlainText(str(template.get("description", "")))
            self.filename_input.setText(str(output.get("filename_pattern", "{{template.name}}.docx")))
            self.folder_pattern_input.setText(str(output.get("folder_pattern", "")))
            self.numbering_checkbox.setChecked(bool(numbering.get("enabled", False)))
            self.numbering_key_input.setText(str(numbering.get("key", "")))
            self.numbering_padding_input.setValue(int(numbering.get("padding", 4) or 4))

            self.selected_docx = self.repository.get_source_path(self.template_id)
            self.selected_input_file = self.selected_docx
            self.selected_input_was_pdf = False
            self._source_field_hints = []
            self._refresh_selected_file_ui()
            self._refresh_duplicate_status()

            fields = [dict(field) for field in config.get("fields", [])]
            section_by_field: dict[str, str] = {}
            for section in config.get("sections", []):
                if not isinstance(section, dict):
                    continue
                title = str(section.get("title", ""))
                for field_id in section.get("fields", []):
                    section_by_field[str(field_id)] = title
            for field in fields:
                field.setdefault("section", section_by_field.get(str(field.get("id", "")), ""))
            self._load_fields_into_table(fields)
        except Exception as exc:
            show_exception_dialog(
                self,
                "Não foi possível carregar o modelo",
                "O modelo não pôde ser carregado no editor.",
                exc,
                stage="template_editor.load",
                context={"template_id": self.template_id or ""},
            )
            self.reject()

    def _choose_template_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            'Selecionar arquivo de modelo',
            '',
            'Arquivos de modelo (*.docx *.pdf);;Documentos do Word (*.docx);;Documentos PDF (*.pdf)',
        )

        if filename:
            self._set_template_file(filename)

    def _set_template_file(
        self,
        filename: str,
    ) -> None:
        source_path = Path(filename).expanduser()

        try:
            prepared = prepare_template_source(
                source_path,
                self.data_dir / 'template_editor_work',
            )
        except TemplateSourceError as exc:
            QMessageBox.warning(
                self,
                'Arquivo não compatível',
                str(exc),
            )
            return

        if prepared.docx_path != prepared.original_path:
            self._automatic_work_files.add(prepared.docx_path)

        self.selected_input_file = prepared.original_path
        self.selected_input_was_pdf = prepared.converted_from_pdf
        self.selected_docx = prepared.docx_path
        self._source_field_hints = [
            *[dict(field) for field in prepared.native_pdf_field_hints],
            *[dict(field) for field in prepared.native_word_field_hints],
        ]
        self.docx_was_replaced = True

        if self.template_id is None and not self.name_input.text().strip():
            suggested_name = (
                prepared.original_path.stem
                .replace('_', ' ')
                .replace('-', ' ')
                .strip()
                .title()
            )
            self.name_input.setText(suggested_name)

        self._refresh_selected_file_ui()
        self._refresh_duplicate_status()

        if prepared.converted_from_pdf:
            details = (
                'O PDF foi convertido para uma cópia DOCX de trabalho para que o mesmo '
                'scanner de campos, prévia e gerador possam ser usados.'
            )
            if prepared.warnings:
                details += ' ' + ' '.join(prepared.warnings[:2])
            show_toast(
                self,
                'PDF preparado para análise',
                details,
                duration=7000,
            )

        elif prepared.prepared_work_copy and prepared.warnings:
            show_toast(
                self,
                'Controles do Word preparados automaticamente',
                ' '.join(prepared.warnings[:2]),
                duration=7000,
            )

        found_fields = True
        if self.template_id is None or self.fields_table.rowCount() == 0:
            found_fields = self._smart_scan_fields(show_message=False)
        if prepared.converted_from_pdf and not found_fields:
            QTimer.singleShot(0, self._detect_fields_without_tags)
        self._schedule_editor_change()
        self._update_readiness()

    def _refresh_selected_file_ui(self) -> None:
        display_path = self.selected_input_file or self.selected_docx
        if display_path is None:
            self.docx_input.clear()
            return

        self.docx_drop_zone.set_selected_file(display_path)
        if self.selected_input_was_pdf and self.selected_docx is not None:
            self.docx_input.setText(
                f'{display_path}  →  DOCX de trabalho: {self.selected_docx.name}'
            )
            self.docx_input.setToolTip(
                f'PDF original: {display_path}\nDOCX de trabalho: {self.selected_docx}'
            )
        else:
            self.docx_input.setText(str(display_path))
            self.docx_input.setToolTip(str(display_path))

    def _refresh_similar_name_status(self) -> None:
        self._similar_name_matches = []
        name = self.name_input.text().strip()

        if not name:
            self.similar_name_warning_label.hide()
            return

        self._similar_name_matches = (
            self.repository.find_templates_with_similar_name(
                name,
                exclude_template_id=self.template_id,
            )
        )
        if not self._similar_name_matches:
            self.similar_name_warning_label.hide()
            return

        descriptions = []
        for match in self._similar_name_matches:
            percentage = round(
                float(match.get("similarity", 0.0)) * 100
            )
            descriptions.append(
                f"{match.get('name', match.get('id', 'Desconhecido'))} "
                f"({percentage}% de semelhança)"
            )

        self.similar_name_warning_label.setText(
            "⚠ Nome de modelo semelhante detectado: "
            + ", ".join(descriptions)
        )
        self.similar_name_warning_label.setToolTip(
            "\n".join(
                f"{match.get('name', match.get('id', 'Desconhecido'))}: "
                f"{round(float(match.get('similarity', 0.0)) * 100)}% — "
                f"{match.get('similarity_reason', 'nome semelhante')}"
                for match in self._similar_name_matches
            )
        )
        self.similar_name_warning_label.show()

    def _confirm_similar_name(self) -> bool:
        name = self.name_input.text().strip()
        name_changed = (
            self.template_id is None
            or self.repository.normalize_template_name(name)
            != self.repository.normalize_template_name(
                self._original_template_name
            )
        )
        if not name_changed:
            return True

        self._refresh_similar_name_status()
        if not self._similar_name_matches:
            return True

        lines = "\n".join(
            f"• {match.get('name', match.get('id', 'Modelo desconhecido'))} "
            f"— {round(float(match.get('similarity', 0.0)) * 100)}% de semelhança"
            for match in self._similar_name_matches
        )
        answer = QMessageBox.question(
            self,
            'Nome de modelo semelhante',
            f'O nome "{name}" é semelhante a modelos existentes:\n\n'
            f"{lines}\n\nSalvar este nome de modelo mesmo assim?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _refresh_duplicate_status(self) -> None:
        self._duplicate_matches = []

        if self.selected_docx is None:
            self.duplicate_warning_label.hide()
            return

        try:
            self._duplicate_matches = (
                self.repository.find_templates_using_docx(
                    self.selected_docx,
                    exclude_template_id=self.template_id,
                )
            )
        except Exception:
            self.duplicate_warning_label.hide()
            return

        if not self._duplicate_matches:
            self.duplicate_warning_label.hide()
            return

        names = ", ".join(
            str(match.get("name", match.get("id", 'Modelo desconhecido')))
            for match in self._duplicate_matches
        )
        count = len(self._duplicate_matches)
        self.duplicate_warning_label.setText(
            f"⚠ Arquivo de modelo repetido detectado. "
            f"Este DOCX já é usado por {count} modelo(s): {names}"
        )
        self.duplicate_warning_label.setToolTip(
            "\n".join(
                f"{match.get('name', match.get('id', 'Desconhecido'))}: "
                f"{match.get('source_path', '')}"
                for match in self._duplicate_matches
            )
        )
        self.duplicate_warning_label.show()

    def _confirm_duplicate_docx(self) -> bool:
        should_check = (
            self.template_id is None
            or self.docx_was_replaced
        )
        if not should_check or self.selected_docx is None:
            return True

        self._refresh_duplicate_status()
        if not self._duplicate_matches:
            return True

        names = "\n".join(
            f"• {match.get('name', match.get('id', 'Modelo desconhecido'))}"
            for match in self._duplicate_matches
        )
        answer = QMessageBox.question(
            self,
            'Arquivo de modelo repetido',
            "O arquivo selecionado possui o mesmo conteúdo de um modelo existente. "
            f"\n\n{names}\n\n"
            "Criar outro modelo usando este mesmo arquivo?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _scan_fields(self) -> None:
        self._smart_scan_fields(show_message=True)

    def _smart_scan_fields(self, *, show_message: bool) -> bool:
        if self.selected_docx is None:
            if show_message:
                QMessageBox.warning(self, 'Nenhum arquivo selecionado', 'Selecione primeiro um arquivo DOCX ou PDF.')
            return False
        repair_result = None
        try:
            # A previous/partial automatic-detection run can leave the editor's
            # working DOCX with duplicate repeatable-column markers. Repair
            # only structurally unambiguous cases before the normal scanner is
            # allowed to validate the document. The original user file is not
            # edited here; ``selected_docx`` is the editor work copy.
            repair_result = repair_repeatable_table_markers(Path(self.selected_docx))
            if repair_result.changed:
                clear_docx_scan_cache()

            existing = self._collect_fields(validate=False)
            # Native PDF form fields have technical AcroForm names that are
            # intentionally different from the human labels printed on the
            # page.  Seed the first/next scans with those source hints while
            # letting any manual edits already present in the editor win.
            seeded_existing = [*self._source_field_hints, *existing]
            fields = smart_fields_from_docx(self.selected_docx, seeded_existing)
        except Exception as exc:
            if show_message:
                show_exception_dialog(
                    self,
                    'Não foi possível analisar o arquivo',
                    'A análise automática do modelo falhou.',
                    exc,
                    stage='template_editor.smart_scan',
                    context={"source": self.selected_docx or ""},
                )
            return False
        if not fields:
            if show_message:
                QMessageBox.warning(
                    self,
                    'Nenhum campo encontrado',
                    (
                        'Nenhuma tag ou controle reconhecido foi encontrado.\n\n'
                        'Use Ferramentas do arquivo > Detectar campos sem tags para receber '
                        'sugestões de áreas preenchíveis.'
                    ),
                )
            return False
        self._load_fields_into_table(fields)
        self._schedule_editor_change()
        self._update_readiness()
        if show_message:
            contextual_labels = sum(
                1
                for field in fields
                if str(field.get("label_source", ""))
                == "document_context"
            )
            specialized_types = sum(
                1
                for field in fields
                if str(field.get("type", "text"))
                not in {"text", "multiline"}
            )
            details = (
                f"{len(fields)} campo(s) configurados; "
                f"{contextual_labels} rótulo(s) lidos do documento e "
                f"{specialized_types} tipo(s) especializado(s)."
            )
            if repair_result is not None and repair_result.changed:
                details += (
                    f" {repair_result.marker_count} marcador(es) de tabela "
                    "repetível foram corrigidos automaticamente."
                )
            show_toast(
                self,
                'Análise inteligente concluída',
                details,
            )
        return True

    def _detect_fields_without_tags(self) -> None:
        if self.selected_docx is None:
            QMessageBox.warning(
                self,
                'Nenhum arquivo selecionado',
                'Selecione primeiro um arquivo DOCX ou PDF.',
            )
            return

        if self._detection_thread is not None and self._detection_thread.isRunning():
            QMessageBox.information(
                self,
                'Detecção em andamento',
                'Aguarde a análise atual terminar ou use Cancelar na janela de progresso.',
            )
            return

        existing = self._collect_fields(validate=False)
        existing_ids = {
            str(field.get('id', '')).strip()
            for field in existing
            if str(field.get('id', '')).strip()
        }

        progress = QProgressDialog(
            'Analisando texto, tabelas, opções e contexto do documento…',
            'Cancelar',
            0,
            0,
            self,
        )
        progress.setWindowTitle('Detectando campos sem tags')
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        thread = QThread(self)
        worker = _AutomaticDetectionWorker(
            self.selected_docx,
            existing_ids,
            existing,
        )
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.result_ready.connect(self._automatic_detection_ready)
        worker.failed.connect(self._automatic_detection_failed)
        worker.canceled.connect(self._automatic_detection_canceled)

        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._automatic_detection_thread_finished)
        progress.canceled.connect(self._request_automatic_detection_cancel)

        self._detection_thread = thread
        self._detection_worker = worker
        self._detection_progress = progress
        progress.show()
        thread.start()

    def _request_automatic_detection_cancel(self) -> None:
        worker = self._detection_worker
        if worker is None:
            return
        worker.request_cancel()
        if self._detection_progress is not None:
            self._detection_progress.setLabelText(
                'Cancelando a detecção com segurança…'
            )
            self._detection_progress.setCancelButtonText("Cancelando…")

    def _automatic_detection_thread_finished(self) -> None:
        if self._detection_progress is not None:
            self._detection_progress.close()
            self._detection_progress.deleteLater()
        self._detection_progress = None
        self._detection_worker = None
        self._detection_thread = None

    def _automatic_detection_failed(self, exc: object) -> None:
        if self._detection_progress is not None:
            self._detection_progress.close()
        error = exc if isinstance(exc, Exception) else RuntimeError(str(exc))
        show_exception_dialog(
            self,
            'Não foi possível detectar áreas preenchíveis',
            'A detecção assistida não conseguiu analisar o documento.',
            error,
            stage='template_editor.automatic_detection',
            context={"source": self.selected_docx or ""},
        )

    def _automatic_detection_canceled(self) -> None:
        if self._detection_progress is not None:
            self._detection_progress.close()
        show_toast(
            self,
            'Detecção cancelada',
            'Nenhuma alteração foi aplicada ao modelo.',
            kind='info',
        )

    def _automatic_detection_ready(self, payload: object) -> None:
        if self._detection_progress is not None:
            self._detection_progress.close()
        candidates: object = []
        existing: list[dict[str, Any]] = []
        scan_report: dict[str, Any] = {}
        if isinstance(payload, tuple) and len(payload) in {2, 3}:
            candidates = payload[0]
            existing = [
                dict(field)
                for field in (payload[1] if isinstance(payload[1], list) else [])
                if isinstance(field, dict)
            ]
            if len(payload) == 3 and isinstance(payload[2], dict):
                scan_report = dict(payload[2])
        values = [
            dict(candidate)
            for candidate in (candidates if isinstance(candidates, list) else [])
            if isinstance(candidate, dict)
        ]
        self._write_scanner_telemetry(scan_report, values)
        if not values:
            QMessageBox.information(
                self,
                'Nenhuma sugestão encontrada',
                (
                    'O documento não contém áreas não marcadas que possam ser '
                    'identificadas com segurança. As tags e controles existentes '
                    'continuam disponíveis em Localizar campos.'
                ),
            )
            return
        self._review_detected_candidates(values, existing, scan_report)

    def _write_scanner_telemetry(
        self,
        report: dict[str, Any],
        candidates: list[dict[str, Any]],
    ) -> None:
        """Persist local scanner diagnostics without document/form contents."""

        try:
            path = self.data_dir / "logs" / "scanner-last.json"
            atomic_write_json(
                path,
                {
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                    "source": str(self.selected_docx or ""),
                    "report": dict(report or {}),
                    "candidates": [
                        {
                            "field_id": str(item.get("field_id", "")),
                            "label": str(item.get("label", "")),
                            "type": str(item.get("type", "")),
                            "source": str(item.get("source", "")),
                            "section": str(item.get("section", "")),
                            "confidence": float(item.get("confidence", 0.0) or 0.0),
                            "confidence_dimensions": dict(item.get("confidence_dimensions", {}) or {}),
                            "review_priority": str(item.get("review_priority", "")),
                            "location": dict(item.get("location", {}) or {}),
                        }
                        for item in candidates
                    ],
                },
            )
        except Exception:
            # Diagnostics must never make field detection fail.
            pass

    def _review_detected_candidates(
        self,
        candidates: list[dict[str, Any]],
        existing: list[dict[str, Any]],
        scan_report: dict[str, Any] | None = None,
    ) -> None:
        dialog = AutomaticDetectionDialog(candidates, self, scan_report=scan_report)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        accepted = dialog.accepted_candidates()
        if not accepted:
            return

        work_path: Path | None = None
        try:
            work_dir = self.data_dir / 'template_editor_work'
            work_dir.mkdir(parents=True, exist_ok=True)
            stem = self.selected_docx.stem[:80] if self.selected_docx is not None else 'modelo'
            stem = stem or 'modelo'
            work_path = work_dir / f'{stem}-detectado-{uuid4().hex[:10]}.docx'
            if self.selected_docx is None:
                raise RuntimeError('O arquivo do modelo deixou de estar disponível durante a revisão.')
            apply_docx_field_candidates(
                self.selected_docx,
                work_path,
                accepted,
            )
            detected_fields = candidate_field_definitions(accepted)
            fields = smart_fields_from_docx(
                work_path,
                [*existing, *detected_fields],
            )
        except Exception as exc:
            if work_path is not None:
                try:
                    work_path.unlink(missing_ok=True)
                except Exception:
                    pass
            show_exception_dialog(
                self,
                'Não foi possível preparar o modelo',
                'As sugestões aprovadas não puderam ser aplicadas ao documento.',
                exc,
                stage='template_editor.apply_detection',
                context={"source": self.selected_docx or ""},
            )
            return

        self._automatic_work_files.add(work_path)
        self.selected_docx = work_path
        self.docx_was_replaced = True
        self._refresh_selected_file_ui()
        self._load_fields_into_table(fields)
        self._refresh_duplicate_status()
        self._schedule_editor_change()
        self._update_readiness()

        show_toast(
            self,
            'Sugestões aplicadas',
            (
                f'{len(accepted)} área(s) aprovada(s) foram convertidas em tags '
                'numa cópia de trabalho. Revise Campos e seções e ajuste somente o que for necessário.'
            ),
            duration=6200,
        )

    def _cleanup_automatic_work_files(self) -> None:
        for path in list(self._automatic_work_files):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                continue
            self._automatic_work_files.discard(path)

    def _show_diagnostics(self) -> None:
        if self.selected_docx is None:
            QMessageBox.warning(self, 'Nenhum arquivo selecionado', 'Selecione primeiro um arquivo DOCX ou PDF.')
            return
        try:
            fields = self._collect_fields(validate=False)
            config = {
                "fields": fields,
                "output": {"filename_pattern": self.filename_input.text()},
            }
            report = diagnose_template(config, self.selected_docx)
        except Exception as exc:
            show_exception_dialog(
                self,
                'Falha no diagnóstico',
                'O diagnóstico do modelo não pôde ser concluído.',
                exc,
                stage='template_editor.diagnostics',
                context={"source": self.selected_docx or ""},
            )
            return
        DiagnosticsDialog(
            'Diagnóstico do modelo',
            diagnostics_text(report),
            self,
            report=report,
            on_field_activated=self.focus_field,
        ).exec()

    def _build_filename(self) -> None:
        dialog = FilenameBuilderDialog(self.filename_input.text(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.filename_input.setText(dialog.pattern())

    def _load_fields_into_table(self, fields: list[dict[str, Any]]) -> None:
        previous = self.fields_table.blockSignals(True)
        try:
            self.fields_table.setRowCount(0)
            for field in fields:
                self._insert_field_row(field)
        finally:
            self.fields_table.blockSignals(previous)
        if hasattr(self, "readiness_label"):
            self._update_readiness()
        if hasattr(self, "simple_fields_checkbox"):
            self._set_simple_fields_mode(self.simple_fields_checkbox.isChecked())
        if hasattr(self, "field_search_input"):
            self._refresh_field_validation()
            self._apply_field_filters()

    def _insert_field_row(self, field: dict[str, Any] | None = None) -> None:
        field = field or {}
        row = self.fields_table.rowCount()
        self.fields_table.insertRow(row)
        id_item = QTableWidgetItem(
            str(field.get("id", ""))
        )
        id_item.setData(Qt.ItemDataRole.UserRole, deepcopy(field))
        label_item = QTableWidgetItem(
            str(field.get("label", ""))
        )
        label_source = str(
            field.get("label_source", "")
        )
        if label_source == "document_context":
            label_item.setToolTip(
                "Rótulo identificado no texto imediatamente antes "
                "do marcador no documento modelo."
            )
        else:
            label_item.setToolTip(
                "Rótulo exibido no formulário. Pode ser editado "
                "sem alterar o identificador do marcador."
            )
        self.fields_table.setItem(row, 0, id_item)
        self.fields_table.setItem(row, 1, label_item)

        type_combo = QComboBox()
        for field_type_key in self.FIELD_TYPES:
            type_combo.addItem(
                self.FIELD_TYPE_LABELS.get(
                    field_type_key,
                    field_type_key,
                ),
                field_type_key,
            )
        field_type = str(field.get("type", "text"))
        index = type_combo.findData(field_type)
        type_combo.setCurrentIndex(index if index >= 0 else 0)
        if str(field.get("type_source", "")) in {
            "document_context",
            "automatic",
            "identifier",
        }:
            type_combo.setToolTip(
                "Tipo sugerido automaticamente pelo identificador "
                "e pelo rótulo encontrado no DOCX. Revise e altere "
                "quando necessário."
            )
        else:
            type_combo.setToolTip(
                "Escolha o controle e a validação usados no formulário."
            )
        self.fields_table.setCellWidget(row, 2, type_combo)

        required = QCheckBox()
        required.setChecked(bool(field.get("required", True)))
        required_container = self._centered_checkbox(required)
        self.fields_table.setCellWidget(row, 3, required_container)

        configuration = FieldConfigurationEditor(
            field_type,
            options=field.get("options", []),
            columns=field.get("columns", []),
            minimum_rows=int(field.get("minimum_rows", 1) or 0),
            numbering_padding=int(field.get("numbering_padding", 2) or 2),
        )
        self.fields_table.setCellWidget(row, 4, configuration)
        self.fields_table.setItem(row, 5, QTableWidgetItem(str(field.get("section", ""))))
        self.fields_table.setItem(row, 6, QTableWidgetItem(str(field.get("profile_key", ""))))
        self.fields_table.setItem(row, 7, QTableWidgetItem(str(field.get("group", ""))))

        single = QCheckBox()
        single.setChecked(str(field.get("selection", "")).casefold() in {"single", "exclusive", "radio"})
        self.fields_table.setCellWidget(row, 8, self._centered_checkbox(single))

        visible = field.get("visible_when", "")
        if isinstance(visible, dict):
            if "equals" in visible:
                visible = f"{visible.get('field', '')}={visible.get('equals', '')}"
            else:
                visible = ""
        self.fields_table.setItem(row, 9, QTableWidgetItem(str(visible)))

        layout_editor = FieldLayoutEditor(field)
        self.fields_table.setCellWidget(row, 10, layout_editor)
        status_item = QTableWidgetItem('OK')
        status_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        status_item.setData(Qt.ItemDataRole.UserRole, 'ok')
        self.fields_table.setItem(row, 11, status_item)

        type_combo.currentIndexChanged.connect(
            lambda _index, combo=type_combo, configuration_widget=configuration, required_widget=required, single_widget=single: self._type_changed(
                str(combo.currentData() or "text"),
                configuration_widget,
                required_widget,
                single_widget,
            )
        )
        type_combo.currentIndexChanged.connect(
            self._schedule_editor_change
        )
        configuration.configuration_changed.connect(self._schedule_editor_change)
        required.toggled.connect(self._schedule_editor_change)
        single.toggled.connect(self._schedule_editor_change)
        layout_editor.configuration_changed.connect(self._schedule_editor_change)
        self._type_changed(field_type, configuration, required, single)

    @staticmethod
    def _centered_checkbox(checkbox: QCheckBox) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(checkbox)
        return container

    def _type_changed(
        self,
        field_type: str,
        configuration: FieldConfigurationEditor,
        required: QCheckBox,
        single: QCheckBox,
    ) -> None:
        configuration.set_field_type(field_type)
        is_checkbox = field_type == "checkbox"
        if is_checkbox:
            required.setChecked(False)
        required.setEnabled(not is_checkbox)
        single.setEnabled(is_checkbox)
        if not is_checkbox:
            single.setChecked(False)

    def _add_empty_field(self) -> None:
        self._insert_field_row({"type": "text", "required": True})

    def _remove_selected_fields(self) -> None:
        rows = {index.row() for index in self.fields_table.selectionModel().selectedRows()}
        if not rows and self.fields_table.currentRow() >= 0:
            rows.add(self.fields_table.currentRow())
        for row in sorted(rows, reverse=True):
            self.fields_table.removeRow(row)

    def _move_selected(self, direction: int) -> None:
        row = self.fields_table.currentRow()
        target = row + direction
        if row < 0 or target < 0 or target >= self.fields_table.rowCount():
            return
        fields = self._collect_fields(validate=False)
        fields[row], fields[target] = fields[target], fields[row]
        self._load_fields_into_table(fields)
        self.fields_table.selectRow(target)

    def _checkbox_at(self, row: int, column: int) -> QCheckBox | None:
        container = self.fields_table.cellWidget(row, column)
        return container.findChild(QCheckBox) if container is not None else None

    @staticmethod
    def _parse_visible_when(value: str) -> dict[str, Any] | None:
        text = value.strip()
        if not text or "=" not in text:
            return None
        field_id, expected = text.split("=", 1)
        expected_text = expected.strip()
        if expected_text.casefold() in {"true", "yes", "sim", "checked", "1"}:
            expected_value: Any = True
        elif expected_text.casefold() in {"false", "no", "nao", "não", "0"}:
            expected_value = False
        else:
            expected_value = expected_text
        return {"field": field_id.strip(), "equals": expected_value}

    def _collect_fields(self, *, validate: bool) -> list[dict[str, Any]]:
        fields: list[dict[str, Any]] = []
        seen: set[str] = set()

        for row in range(self.fields_table.rowCount()):
            id_item = self.fields_table.item(row, 0)
            label_item = self.fields_table.item(row, 1)
            type_combo = self.fields_table.cellWidget(row, 2)
            configuration_input = self.fields_table.cellWidget(row, 4)
            section_item = self.fields_table.item(row, 5)
            profile_item = self.fields_table.item(row, 6)
            group_item = self.fields_table.item(row, 7)
            visible_item = self.fields_table.item(row, 9)
            layout_input = self.fields_table.cellWidget(row, 10)
            required = self._checkbox_at(row, 3)
            single = self._checkbox_at(row, 8)

            field_id = id_item.text().strip() if id_item else ""
            label = label_item.text().strip() if label_item else ""
            field_type = (
                str(type_combo.currentData() or "text")
                if isinstance(type_combo, QComboBox)
                else "text"
            )

            if not field_id and not label:
                if validate:
                    raise ValueError(
                        f"A linha de campo {row + 1} está vazia. Preencha o campo ou remova a linha."
                    )
                continue
            if validate and not field_id:
                raise ValueError(f"A linha de campo {row + 1} não possui ID.")
            if validate and field_id in seen:
                raise ValueError(f"ID de campo duplicado: {field_id}")
            seen.add(field_id)

            original = (
                id_item.data(Qt.ItemDataRole.UserRole)
                if id_item is not None
                else {}
            )
            original = deepcopy(original) if isinstance(original, dict) else {}
            # Preserve semantic metadata that is not represented by an
            # editable table column.  This is especially important for
            # automatically detected checkbox groups embedded in a document
            # grid: ``choice_group_label`` is the local question (for example
            # "Há impedimento conhecido?"), while ``layout_group_label`` is
            # the surrounding section title.
            field: dict[str, Any] = preserved_editor_field_metadata(original)
            field.update(
                {
                    "id": field_id,
                    "label": label or field_id.replace(".", " ").replace("_", " ").title(),
                    "type": field_type,
                    "required": False if field_type == "checkbox" else bool(required and required.isChecked()),
                }
            )

            if field_type == "dropdown":
                options = (
                    configuration_input.options()
                    if isinstance(configuration_input, FieldConfigurationEditor)
                    else []
                )
                if validate and len(options) < 2:
                    raise ValueError(
                        f"A lista suspensa '{field_id}' exige pelo menos duas opções."
                    )
                field["options"] = options
            if field_type == "repeatable_table":
                columns = (
                    configuration_input.columns()
                    if isinstance(configuration_input, FieldConfigurationEditor)
                    else []
                )
                if validate and not columns:
                    raise ValueError(
                        f"A tabela repetível '{field_id}' exige pelo menos uma coluna."
                    )
                field["columns"] = columns
                field["minimum_rows"] = (
                    configuration_input.minimum_rows()
                    if isinstance(configuration_input, FieldConfigurationEditor)
                    else 1
                )
                field["numbering_padding"] = (
                    configuration_input.numbering_padding()
                    if isinstance(configuration_input, FieldConfigurationEditor)
                    else 2
                )
            if field_type == "date":
                # Preserve whether this specific date is automatic. Assisted
                # detection marks date fill areas as editable (False), while
                # legacy/system dates may explicitly opt into automatic today.
                field["automatic"] = bool(original.get("automatic", False))

            section = section_item.text().strip() if section_item else ""
            profile_key = profile_item.text().strip() if profile_item else ""
            group = group_item.text().strip() if group_item else ""
            visible_text = visible_item.text().strip() if visible_item else ""
            visible = self._parse_visible_when(visible_text)
            if validate and visible_text and visible is None:
                raise ValueError(
                    f"A regra de visibilidade do campo '{field_id}' é inválida. "
                    "Use o formato campo=valor."
                )
            if section:
                field["section"] = section
                original_section = str(original.get("section", "") or "").strip()
                if section != original_section:
                    field["section_source"] = "manual"
            if profile_key:
                field["profile_key"] = profile_key
            if group:
                field["group"] = group
            if field_type == "checkbox" and single and single.isChecked():
                field["selection"] = "single"
            if visible:
                field["visible_when"] = visible
            elif visible_text:
                # Preserve unfinished rules in editor snapshots so live
                # validation/undo never silently discards what the author typed.
                field["visible_when"] = visible_text

            if isinstance(layout_input, FieldLayoutEditor):
                layout_config = layout_input.configuration()
                layout_type = str(layout_config.pop("layout", "auto")).strip() or "auto"
                if layout_type != "auto":
                    field["layout"] = layout_type
                if layout_type == "full_width":
                    field["full_width"] = True
                for key, value in layout_config.items():
                    if value not in (None, "", False):
                        field[key] = value
                if layout_type == "choice" and field_type in {"checkbox", "dropdown"}:
                    layout_group = str(field.get("layout_group", "")).strip()
                    if field_type == "dropdown" and not layout_group:
                        layout_group = f"single_choice_{field_id}"
                        field["layout_group"] = layout_group
                    if layout_group:
                        field["group"] = layout_group
                    field["selection"] = "single"
                    if field_type == "dropdown" and bool(field.get("required", False)):
                        field["choice_required"] = True

                if validate and layout_type == "choice":
                    if field_type not in {"checkbox", "dropdown"}:
                        raise ValueError(
                            f"O campo '{field_id}' usa Grupo de escolha, mas não é uma caixa de seleção nem uma lista de opções."
                        )
                    if not str(field.get("layout_group", "")).strip():
                        raise ValueError(
                            f"O campo '{field_id}' precisa de um Grupo do layout para formar uma escolha exclusiva."
                        )
                if validate and layout_type == "form_grid":
                    missing_layout = [
                        label
                        for key, label in (
                            ("layout_group", "Grupo do layout"),
                            ("layout_row", "Chave da linha"),
                        )
                        if not str(field.get(key, "")).strip()
                    ]
                    if missing_layout:
                        raise ValueError(
                            f"O campo '{field_id}' precisa configurar em Layout > Detalhes: "
                            + ", ".join(missing_layout)
                            + "."
                        )

                if validate and layout_type == "table":
                    missing_layout = [
                        label
                        for key, label in (
                            ("layout_group", "Grupo do layout"),
                            ("layout_row", "Chave da linha"),
                            ("layout_column", "Rótulo da coluna"),
                        )
                        if not str(field.get(key, "")).strip()
                    ]
                    if missing_layout:
                        raise ValueError(
                            f"O campo '{field_id}' precisa configurar em Layout > Detalhes: "
                            + ", ".join(missing_layout)
                            + "."
                        )

            fields.append(field)

        fields = normalize_form_layout(fields)

        if validate:
            choice_groups: dict[str, list[dict[str, Any]]] = {}
            table_groups: dict[str, list[str]] = {}
            for field in fields:
                layout_type = str(field.get("layout", "auto")).strip()
                group = str(field.get("layout_group", "")).strip()
                if layout_type == "choice" and group:
                    choice_groups.setdefault(group, []).append(field)
                elif layout_type == "table" and group:
                    table_groups.setdefault(group, []).append(str(field.get("id", "")))
            for group, group_fields in choice_groups.items():
                dropdown_fields = [
                    field for field in group_fields
                    if str(field.get("type", "")).strip() == "dropdown"
                ]
                if len(group_fields) == 1 and dropdown_fields:
                    if len(dropdown_fields[0].get("options", [])) < 2:
                        raise ValueError(
                            f"O Grupo de escolha '{group}' precisa conter pelo menos duas opções."
                        )
                    continue
                if len(group_fields) < 2:
                    raise ValueError(
                        f"O Grupo de escolha '{group}' precisa conter pelo menos duas opções."
                    )
            for group, field_ids in table_groups.items():
                if len(field_ids) < 2:
                    raise ValueError(
                        f"A Tabela '{group}' precisa conter pelo menos dois campos."
                    )

            layout_issues = layout_quality_issues(fields)
            if layout_issues:
                raise ValueError(
                    "A organização visual possui conflitos:\n- "
                    + "\n- ".join(layout_issues)
                    + "\nRevise Campos e seções > Prévia do formulário."
                )

        return fields

    @staticmethod
    def _build_sections(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
        section_map: dict[str, list[str]] = {}
        order: list[str] = []
        for field in fields:
            title = str(field.get("section", "")).strip() or 'Dados do documento'
            if title not in section_map:
                section_map[title] = []
                order.append(title)
            section_map[title].append(str(field["id"]))
        return [{"title": title, "fields": section_map[title]} for title in order]

    def _connect_change_tracking(self) -> None:
        for widget in (
            self.name_input,
            self.category_input,
            self.version_input,
            self.filename_input,
            self.folder_pattern_input,
            self.numbering_key_input,
        ):
            widget.textChanged.connect(self._schedule_editor_change)
        self.description_input.textChanged.connect(self._schedule_editor_change)
        self.numbering_checkbox.toggled.connect(self._schedule_editor_change)
        self.numbering_padding_input.valueChanged.connect(self._schedule_editor_change)
        self.fields_table.cellChanged.connect(self._schedule_editor_change)

    def _schedule_editor_change(self, *_args) -> None:
        if self._applying_snapshot:
            return
        self._dirty = True
        self.change_timer.start()
        if hasattr(self, "readiness_label"):
            self._update_readiness()

    def _snapshot_editor_state(self) -> dict[str, Any]:
        return {
            "name": self.name_input.text(),
            "category": self.category_input.text(),
            "version": self.version_input.text(),
            "description": self.description_input.toPlainText(),
            "docx": str(self.selected_docx or ""),
            "input_file": str(self.selected_input_file or ""),
            "input_was_pdf": self.selected_input_was_pdf,
            "filename_pattern": self.filename_input.text(),
            "folder_pattern": self.folder_pattern_input.text(),
            "numbering_enabled": self.numbering_checkbox.isChecked(),
            "numbering_key": self.numbering_key_input.text(),
            "numbering_padding": self.numbering_padding_input.value(),
            "fields": self._collect_fields(validate=False),
        }

    def _commit_editor_change(self) -> None:
        if self._applying_snapshot:
            return
        snapshot = self._snapshot_editor_state()
        if self._history and self._history[self._history_index] == snapshot:
            self._write_editor_draft(snapshot)
            return
        self._history = self._history[: self._history_index + 1]
        self._history.append(deepcopy(snapshot))
        self._history = self._history[-80:]
        self._history_index = len(self._history) - 1
        self._write_editor_draft(snapshot)
        self._update_undo_buttons()

    def _write_editor_draft(self, snapshot: dict[str, Any]) -> None:
        self.editor_draft_path.parent.mkdir(parents=True, exist_ok=True)
        self.editor_draft_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _recover_editor_draft(self) -> None:
        if not self.editor_draft_path.exists():
            self._update_undo_buttons()
            return
        try:
            snapshot = json.loads(self.editor_draft_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._update_undo_buttons()
            return
        if not isinstance(snapshot, dict) or snapshot == self._initial_snapshot:
            self._update_undo_buttons()
            return
        answer = QMessageBox.question(
            self,
            'Recuperar rascunho do modelo',
            'Foi encontrado um rascunho salvo automaticamente pelo editor. Deseja recuperá-lo?',
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._apply_editor_snapshot(snapshot)
            self._dirty = True
            self._history.append(deepcopy(snapshot))
            self._history_index = len(self._history) - 1
        else:
            self.editor_draft_path.unlink(missing_ok=True)
        self._update_undo_buttons()

    def _apply_editor_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._applying_snapshot = True
        try:
            self.name_input.setText(str(snapshot.get("name", "")))
            self.category_input.setText(str(snapshot.get("category", "")))
            self.version_input.setText(str(snapshot.get("version", "1.0")))
            self.description_input.setPlainText(str(snapshot.get("description", "")))
            docx = Path(str(snapshot.get("docx", ""))) if snapshot.get("docx") else None
            self.selected_docx = docx if docx and docx.exists() else self.selected_docx
            input_file = (
                Path(str(snapshot.get("input_file", "")))
                if snapshot.get("input_file")
                else None
            )
            self.selected_input_file = (
                input_file if input_file and input_file.exists() else self.selected_docx
            )
            self.selected_input_was_pdf = bool(snapshot.get("input_was_pdf", False))
            if self.selected_docx:
                self._refresh_selected_file_ui()
                self._refresh_duplicate_status()
                if self.template_id is None:
                    self.docx_was_replaced = True
                else:
                    try:
                        original = self.repository.get_source_path(self.template_id).resolve()
                        self.docx_was_replaced = self.selected_docx.resolve() != original
                    except Exception:
                        self.docx_was_replaced = True
            self.filename_input.setText(str(snapshot.get("filename_pattern", "{{template.name}}.docx")))
            self.folder_pattern_input.setText(str(snapshot.get("folder_pattern", "")))
            self.numbering_checkbox.setChecked(bool(snapshot.get("numbering_enabled", False)))
            self.numbering_key_input.setText(str(snapshot.get("numbering_key", "")))
            self.numbering_padding_input.setValue(int(snapshot.get("numbering_padding", 4) or 4))
            fields = snapshot.get("fields", [])
            self._load_fields_into_table([dict(field) for field in fields if isinstance(field, dict)])
        finally:
            self._applying_snapshot = False
        self._update_readiness()

    def _undo_editor_change(self) -> None:
        self.change_timer.stop()
        if self._history_index <= 0:
            return
        self._history_index -= 1
        self._apply_editor_snapshot(self._history[self._history_index])
        self._dirty = self._history[self._history_index] != self._initial_snapshot
        self._update_undo_buttons()

    def _redo_editor_change(self) -> None:
        self.change_timer.stop()
        if self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        self._apply_editor_snapshot(self._history[self._history_index])
        self._dirty = self._history[self._history_index] != self._initial_snapshot
        self._update_undo_buttons()

    def _update_undo_buttons(self) -> None:
        self.undo_button.setEnabled(self._history_index > 0)
        self.redo_button.setEnabled(self._history_index < len(self._history) - 1)
        self.revert_button.setEnabled(bool(self._dirty))

    def _revert_editor_changes(self) -> None:
        if self._initial_snapshot is None:
            return
        answer = QMessageBox.question(
            self,
            'Reverter alterações',
            'Descartar todas as alterações feitas desde que o editor foi aberto?',
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._apply_editor_snapshot(deepcopy(self._initial_snapshot))
        self._history = [deepcopy(self._initial_snapshot)]
        self._history_index = 0
        self._dirty = False
        self.editor_draft_path.unlink(missing_ok=True)
        self._update_undo_buttons()

    def _insert_field_group(self) -> None:
        dialog = FieldLibraryDialog(self.field_library, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        existing_ids = {str(field.get("id", "")) for field in self._collect_fields(validate=False)}
        inserted = 0
        skipped: list[str] = []
        for field in dialog.selected_fields:
            field_id = str(field.get("id", ""))
            if field_id in existing_ids:
                skipped.append(field_id)
                continue
            self._insert_field_row(dict(field))
            existing_ids.add(field_id)
            inserted += 1
        self._schedule_editor_change()
        message = f"Foram inseridos {inserted} campo(s)."
        if skipped:
            message += "\nIDs existentes ignorados: " + ", ".join(skipped)
        show_toast(
            self,
            'Grupo de campos inserido',
            message,
            kind='warning' if skipped else 'success',
        )

    def _save_selected_field_group(self) -> None:
        rows = sorted(index.row() for index in self.fields_table.selectionModel().selectedRows())
        if not rows:
            QMessageBox.warning(self, 'Selecionar campos', 'Selecione primeiro uma ou mais linhas de campos.')
            return
        all_fields = self._collect_fields(validate=False)
        selected = [all_fields[row] for row in rows if 0 <= row < len(all_fields)]
        name, accepted = QInputDialog.getText(self, 'Salvar grupo de campos', 'Nome do grupo:')
        if not accepted or not name.strip():
            return
        description, accepted = QInputDialog.getText(self, 'Descrição do grupo de campos', 'Descrição:')
        if not accepted:
            return
        try:
            self.field_library.save_group(name=name.strip(), description=description.strip(), fields=selected)
        except Exception as exc:
            show_exception_dialog(
                self,
                'Não foi possível salvar o grupo',
                'O grupo de campos não pôde ser salvo na biblioteca.',
                exc,
                stage='template_editor.save_field_group',
            )
            return
        show_toast(
            self,
            'Grupo de campos salvo',
            'Os campos selecionados estão disponíveis na Biblioteca de Campos.',
        )

    def _apply_safe_fixes(self) -> None:
        if self.selected_docx is None:
            return
        before = len(self._collect_fields(validate=False))
        self._smart_scan_fields(show_message=False)
        after = len(self._collect_fields(validate=False))
        show_toast(
            self,
            'Correções seguras aplicadas',
            (
                'Os campos foram sincronizados com o arquivo do modelo. '
                f'A contagem mudou em {after - before:+d} e os metadados personalizados foram preservados.'
            ),
            duration=5200,
        )

    def _update_readiness(self) -> None:
        if not hasattr(self, "readiness_label"):
            return
        try:
            report = readiness_report(
                name=self.name_input.text(),
                docx_path=self.selected_docx,
                fields=self._collect_fields(validate=False),
                filename_pattern=self.filename_input.text(),
            )
        except Exception as exc:
            self.readiness_label.setText('O modelo precisa de atenção')
            self.readiness_details.setText(str(exc))
            self.safe_fix_button.setEnabled(False)
            return
        self._refresh_duplicate_status()
        self._refresh_similar_name_status()
        failed = [item for item in report["checks"] if not item.get("ok")]
        if self._similar_name_matches:
            failed.append(
                {
                    "label": "Nome de modelo semelhante",
                    "detail": (
                        "é semelhante a "
                        + ", ".join(
                            str(match.get("name", match.get("id", 'Desconhecido')))
                            for match in self._similar_name_matches
                        )
                    ),
                }
            )

        if self._duplicate_matches:
            failed.append(
                {
                    "label": "DOCX de origem repetido",
                    "detail": (
                        "também usado por "
                        + ", ".join(
                            str(match.get("name", match.get("id", 'Desconhecido')))
                            for match in self._duplicate_matches
                        )
                    ),
                }
            )

        live_errors = []
        if hasattr(self, "fields_table"):
            live_fields = [
                self._field_row_validation_snapshot(row)
                for row in range(self.fields_table.rowCount())
            ]
            live_errors = [
                issue
                for issue in field_configuration_issues(live_fields)
                if issue.severity == "error"
            ]
            if live_errors:
                failed.append(
                    {
                        "label": "Configuração dos campos",
                        "detail": f"{len(live_errors)} erro(s) na validação rápida",
                    }
                )

        if (
            report["ready"]
            and not self._duplicate_matches
            and not self._similar_name_matches
            and not live_errors
        ):
            self.readiness_label.setText("✓ Pronto para salvar")
            self.readiness_details.setText('Todas as verificações obrigatórias foram aprovadas.')
        else:
            self.readiness_label.setText(f"⚠ {len(failed)} item(ns) precisa(m) de atenção")
            self.readiness_details.setText(
                " • ".join(
                    f"{item.get('label')}{': ' + str(item.get('detail')) if item.get('detail') else ''}"
                    for item in failed
                )
            )
        self.safe_fix_button.setEnabled(bool(self.selected_docx))
        if hasattr(self, "fields_table"):
            self._refresh_field_validation()
        if hasattr(self, "fields_tabs"):
            if self.fields_tabs.currentIndex() == 1:
                self._refresh_section_tree()
            elif self.fields_tabs.currentIndex() == 2:
                self._refresh_form_preview()
        self._update_undo_buttons()

    def _cancel_editor(self) -> None:
        if self._detection_thread is not None and self._detection_thread.isRunning():
            self._request_automatic_detection_cancel()
            QMessageBox.information(
                self,
                'Cancelando análise',
                'Aguarde a detecção terminar de cancelar antes de fechar o editor.',
            )
            return
        if self._dirty:
            answer = QMessageBox.question(
                self,
                'Descartar alterações',
                'Fechar o editor de modelo e descartar as alterações não salvas?',
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._dirty = False
        self.change_timer.stop()
        self.editor_draft_path.unlink(missing_ok=True)
        self._cleanup_automatic_work_files()
        self.reject()

    def closeEvent(self, event) -> None:
        if self._detection_thread is not None and self._detection_thread.isRunning():
            self._request_automatic_detection_cancel()
            event.ignore()
            return
        if not self._dirty:
            event.accept()
            return
        answer = QMessageBox.question(
            self,
            'Alterações não salvas',
            'Fechar o editor de modelo? O rascunho salvo automaticamente poderá ser recuperado na próxima vez.',
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._commit_editor_change()
            event.accept()
        else:
            event.ignore()

    def _save_template(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, 'Nome do modelo ausente', 'Informe um nome para o modelo.')
            return
        if self.selected_docx is None:
            QMessageBox.warning(self, 'Arquivo ausente', 'Selecione um arquivo DOCX ou PDF.')
            return
        if not self._confirm_similar_name():
            return
        if not self._confirm_duplicate_docx():
            return

        try:
            fields = self._collect_fields(validate=True)
            sections = self._build_sections(fields)

            preflight = diagnose_template(
                {
                    "fields": fields,
                    "sections": sections,
                    "output": {"filename_pattern": self.filename_input.text()},
                },
                self.selected_docx,
            )
            if preflight.get("blocking"):
                DiagnosticsDialog(
                    'O modelo precisa de correções',
                    diagnostics_text(preflight),
                    self,
                    report=preflight,
                    on_field_activated=self.focus_field,
                ).exec()
                return
            if preflight.get("warning_count", 0):
                warning_box = QMessageBox(self)
                warning_box.setIcon(QMessageBox.Icon.Warning)
                warning_box.setWindowTitle('Avisos no modelo')
                warning_box.setText(
                    f"Foram encontrados {preflight.get('warning_count', 0)} aviso(s). "
                    "Eles não bloqueiam o modelo, mas podem exigir revisão."
                )
                warning_box.setDetailedText(diagnostics_text(preflight))
                warning_box.setStandardButtons(
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel
                )
                warning_box.setDefaultButton(QMessageBox.StandardButton.Cancel)
                if warning_box.exec() != QMessageBox.StandardButton.Save:
                    return

            numbering = {
                "enabled": self.numbering_checkbox.isChecked(),
                "key": self.numbering_key_input.text().strip(),
                "padding": self.numbering_padding_input.value(),
            }

            if self.template_id is None:
                saved_id = self.repository.create_template(
                    name=name,
                    source_docx=self.selected_docx,
                    fields=fields,
                    description=self.description_input.toPlainText(),
                    category=self.category_input.text(),
                    version=self.version_input.text(),
                    filename_pattern=self.filename_input.text(),
                    sections=sections,
                    output_folder_pattern=self.folder_pattern_input.text(),
                    numbering=numbering,
                    allow_similar_name=True,
                )
            else:
                saved_id = self.repository.update_template(
                    template_id=self.template_id,
                    name=name,
                    fields=fields,
                    description=self.description_input.toPlainText(),
                    category=self.category_input.text(),
                    version=self.version_input.text(),
                    filename_pattern=self.filename_input.text(),
                    replacement_docx=self.selected_docx if self.docx_was_replaced else None,
                    sections=sections,
                    output_folder_pattern=self.folder_pattern_input.text(),
                    numbering=numbering,
                    allow_similar_name=True,
                )
        except Exception as exc:
            show_exception_dialog(
                self,
                'Não foi possível salvar o modelo',
                'O modelo não pôde ser salvo. Nenhuma correção automática foi aplicada.',
                exc,
                stage='template_editor.save',
                context={"template_id": self.template_id or "", "source": self.selected_docx or ""},
            )
            return

        self.saved_template_id = saved_id
        self._dirty = False
        self.change_timer.stop()
        self.editor_draft_path.unlink(missing_ok=True)
        self._cleanup_automatic_work_files()
        self.accept()
