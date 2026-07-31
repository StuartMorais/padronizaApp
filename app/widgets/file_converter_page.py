from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSettings,
    QThreadPool,
    QTimer,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.runtime_settings import APPLICATION, ORGANIZATION
from app.system_open import SystemOpenError, open_file, open_folder
from app.widgets.clickable_drop_zone import ClickableDropZone
from app.widgets.context_help import HelpIconButton, HelpLabel
from app.widgets.empty_state import EmptyState

from app.pdf_converter import (
    DocxConversionError,
    PdfConversionError,
    convert_docx_to_pdf,
    convert_pdf_to_docx,
)


class _ConversionSignals(QObject):
    finished = Signal(bool, str, str, str, str)


class _ConversionTask(QRunnable):
    def __init__(
        self,
        *,
        direction: str,
        source: Path,
        destination: Path,
    ) -> None:
        super().__init__()

        self.direction = direction
        self.source = Path(source)
        self.destination = Path(destination)
        self.signals = _ConversionSignals()

    @Slot()
    def run(self) -> None:
        warnings: list[str] = []

        try:
            if self.direction == "docx_to_pdf":
                result = convert_docx_to_pdf(
                    self.source,
                    self.destination,
                    warnings=warnings,
                )
            elif self.direction == "pdf_to_docx":
                result = convert_pdf_to_docx(
                    self.source,
                    self.destination,
                    warnings=warnings,
                )
            else:
                raise ValueError(
                    f"Direção de conversão desconhecida: {self.direction}"
                )
        except (
            PdfConversionError,
            DocxConversionError,
            ValueError,
        ) as exc:
            self.signals.finished.emit(
                False,
                self.direction,
                str(self.source),
                str(self.destination),
                str(exc),
            )
            return
        except Exception as exc:
            self.signals.finished.emit(
                False,
                self.direction,
                str(self.source),
                str(self.destination),
                f"Erro inesperado de conversão: {exc}",
            )
            return

        self.signals.finished.emit(
            True,
            self.direction,
            str(self.source),
            str(result),
            "\n".join(warnings),
        )


class _FileDropZone(ClickableDropZone):
    SUPPORTED_SUFFIXES = frozenset({".docx", ".pdf"})

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self._expected_suffix = ".docx"

        self.setObjectName("conversionDropZone")
        self.setAcceptDrops(True)
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.setMinimumHeight(142)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            22,
            20,
            22,
            20,
        )
        layout.setSpacing(6)
        layout.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.title_label = QLabel(
            "Arraste um arquivo DOCX para cá"
        )
        self.title_label.setObjectName(
            "conversionDropTitle"
        )
        self.title_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.subtitle_label = QLabel(
            "ou selecione um arquivo no computador"
        )
        self.subtitle_label.setObjectName(
            "conversionDropText"
        )
        self.subtitle_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        self.browse_button = self.create_browse_button(
            "Selecionar arquivo"
        )

        self.add_drop_content(
            layout,
            self.title_label,
            self.subtitle_label,
            self.browse_button,
            spacing_before_button=5,
        )

    def set_expected_suffix(
        self,
        suffix: str,
    ) -> None:
        normalized = suffix.lower().strip()
        self._expected_suffix = normalized

        display = normalized.lstrip(".").upper()
        self.title_label.setText(
            f"Arraste um arquivo {display} para cá"
        )

    def set_busy(
        self,
        busy: bool,
    ) -> None:
        self.setEnabled(not busy)
        self.browse_button.setEnabled(not busy)



class FileConverterPage(QWidget):
    conversion_completed = Signal(
        str,
        str,
        str,
    )

    HISTORY_KEY = "conversion/recent"
    HISTORY_LIMIT = 10

    DIRECTIONS = {
        "docx_to_pdf": {
            "source_suffix": ".docx",
            "destination_suffix": ".pdf",
            "label": "DOCX → PDF",
            "button": 'Converter para PDF',
            "filter": "Documento do Word (*.docx)",
            "stages": [
                'Lendo o documento do Word…',
                'Preparando páginas e formatação…',
                'Gerando o PDF…',
                'Finalizando o arquivo convertido…',
            ],
        },
        "pdf_to_docx": {
            "source_suffix": ".pdf",
            "destination_suffix": ".docx",
            "label": "PDF → DOCX",
            "button": 'Converter para DOCX',
            "filter": 'Documento PDF (*.pdf)',
            "stages": [
                'Lendo o PDF…',
                'Extraindo textos, imagens e tabelas…',
                'Criando o documento do Word…',
                'Finalizando o arquivo convertido…',
            ],
        },
    }

    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        self.settings = QSettings(
            ORGANIZATION,
            APPLICATION,
        )
        self._thread_pool = (
            QThreadPool.globalInstance()
        )
        self._busy = False
        self._direction = "docx_to_pdf"
        self._selected_source: Path | None = None
        self._last_output: Path | None = None
        self._active_destination: Path | None = None
        self._progress_stage_index = 0
        self._history = self._load_history()

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(1450)
        self._progress_timer.timeout.connect(
            self._advance_progress_stage
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(
            QFrame.Shape.NoFrame
        )

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(
            22,
            20,
            22,
            26,
        )
        layout.setSpacing(14)

        title = QLabel('Converter arquivos')
        title.setObjectName("pageTitle")

        description = QLabel(
            "Selecione ou arraste um arquivo DOCX ou PDF. "
            "O arquivo convertido recebe um nome automaticamente "
            "e é salvo ao lado do original."
        )
        description.setObjectName("mutedText")
        description.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(
            self._create_mode_panel()
        )

        self.drop_zone = _FileDropZone()
        self.drop_zone.file_dropped.connect(
            self._select_source
        )
        self.drop_zone.browse_requested.connect(
            self._browse_source
        )
        layout.addWidget(
            self.drop_zone
        )

        self.selected_panel = (
            self._create_selected_panel()
        )
        self.selected_panel.setVisible(False)
        layout.addWidget(
            self.selected_panel
        )

        self.status_panel = (
            self._create_status_panel()
        )
        layout.addWidget(
            self.status_panel
        )

        layout.addWidget(
            self._create_history_panel()
        )
        layout.addStretch()

        scroll.setWidget(content)
        root_layout.addWidget(scroll)

        self._set_direction(
            "docx_to_pdf",
            clear_incompatible=False,
        )
        self._refresh_history_table()
        self._show_ready_state()

    def _create_mode_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName(
            "conversionModePanel"
        )

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(
            14,
            12,
            14,
            12,
        )
        layout.setSpacing(10)

        label = QLabel('Tipo de conversão')
        label.setObjectName(
            "conversionModeLabel"
        )

        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)

        self.docx_mode_button = QPushButton(
            "DOCX  →  PDF"
        )
        self.docx_mode_button.setObjectName(
            "conversionModeButton"
        )
        self.docx_mode_button.setCheckable(True)

        self.pdf_mode_button = QPushButton(
            "PDF  →  DOCX"
        )
        self.pdf_mode_button.setObjectName(
            "conversionModeButton"
        )
        self.pdf_mode_button.setCheckable(True)

        self.mode_group.addButton(
            self.docx_mode_button
        )
        self.mode_group.addButton(
            self.pdf_mode_button
        )

        self.docx_mode_button.clicked.connect(
            lambda checked: (
                self._set_direction(
                    "docx_to_pdf",
                    clear_incompatible=True,
                )
                if checked
                else None
            )
        )
        self.pdf_mode_button.clicked.connect(
            lambda checked: (
                self._set_direction(
                    "pdf_to_docx",
                    clear_incompatible=True,
                )
                if checked
                else None
            )
        )

        layout.addWidget(label)
        layout.addWidget(
            self.docx_mode_button
        )
        layout.addWidget(
            self.pdf_mode_button
        )
        layout.addWidget(
            HelpIconButton(
                'Tipos de conversão',
                (
                    '<p><b>DOCX → PDF</b> cria uma versão pronta para leitura e impressão.</p>'
                    '<p><b>PDF → DOCX</b> recupera texto, tabelas e imagens quando possível. '
                    'PDFs digitalizados sem texto selecionável são inseridos como imagens, '
                    'e layouts complexos podem ser simplificados.</p>'
                ),
            )
        )
        layout.addStretch()

        return panel

    def _create_selected_panel(
        self,
    ) -> QGroupBox:
        panel = QGroupBox(
            'Arquivo selecionado'
        )

        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        top_row = QHBoxLayout()

        self.source_name_label = QLabel()
        self.source_name_label.setObjectName(
            "conversionFileName"
        )

        change_button = QPushButton(
            'Selecionar outro arquivo'
        )
        change_button.clicked.connect(
            self._browse_source
        )

        top_row.addWidget(
            self.source_name_label,
            1,
        )
        top_row.addWidget(
            change_button
        )
        top_row.addWidget(
            HelpIconButton(
                'Arquivo de origem e destino',
                (
                    '<p>O arquivo original não é alterado. O resultado é salvo ao lado '
                    'dele com a extensão correspondente.</p>'
                    '<p>Quando o nome já existe, o Padroniza cria uma variação segura, '
                    'como <b>_converted</b> ou <b>_converted_2</b>.</p>'
                ),
            )
        )

        self.source_path_label = QLabel()
        self.source_path_label.setObjectName(
            "conversionPath"
        )
        self.source_path_label.setWordWrap(True)
        self.source_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.direction_label = QLabel()
        self.direction_label.setObjectName(
            "mutedText"
        )

        self.output_preview_label = QLabel()
        self.output_preview_label.setObjectName(
            "conversionOutputPreview"
        )
        self.output_preview_label.setWordWrap(True)
        self.output_preview_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        action_row = QHBoxLayout()
        action_row.addStretch()

        self.convert_button = QPushButton(
            'Converter para PDF'
        )
        self.convert_button.setObjectName(
            "primaryButton"
        )
        self.convert_button.clicked.connect(
            self._start_conversion
        )

        action_row.addWidget(
            self.convert_button
        )

        layout.addLayout(top_row)
        layout.addWidget(
            self.source_path_label
        )
        layout.addWidget(
            self.direction_label
        )
        layout.addWidget(
            HelpLabel(
                'Saída prevista',
                'Nome e local do arquivo convertido',
                (
                    '<p>Esta prévia mostra o caminho que será usado antes da conversão.</p>'
                    '<p>O resultado é criado ao lado do arquivo original e o arquivo de '
                    'origem permanece intacto.</p>'
                ),
            )
        )
        layout.addWidget(
            self.output_preview_label
        )
        layout.addLayout(
            action_row
        )

        self.change_source_button = (
            change_button
        )
        return panel

    def _create_status_panel(
        self,
    ) -> QFrame:
        panel = QFrame()
        panel.setObjectName(
            "conversionStatus"
        )

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(
            16,
            14,
            16,
            14,
        )
        layout.setSpacing(7)

        self.status_title = QLabel(
            'Pronto para converter'
        )
        self.status_title.setObjectName(
            "conversionStatusTitle"
        )

        self.status_detail = QLabel(
            'Selecione um arquivo para começar.'
        )
        self.status_detail.setObjectName(
            "conversionStatusText"
        )
        self.status_detail.setWordWrap(True)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)

        self.result_path_label = QLabel()
        self.result_path_label.setObjectName(
            "conversionResultPath"
        )
        self.result_path_label.setWordWrap(True)
        self.result_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.result_path_label.setVisible(False)

        action_row = QHBoxLayout()

        self.open_output_button = QPushButton(
            'Abrir arquivo'
        )
        self.open_folder_button = QPushButton(
            'Abrir pasta'
        )
        self.convert_another_button = QPushButton(
            'Converter outro'
        )

        self.open_output_button.clicked.connect(
            self._open_last_output
        )
        self.open_folder_button.clicked.connect(
            self._open_last_folder
        )
        self.convert_another_button.clicked.connect(
            self._reset_workflow
        )

        for button in (
            self.open_output_button,
            self.open_folder_button,
            self.convert_another_button,
        ):
            button.setVisible(False)
            action_row.addWidget(button)

        action_row.addStretch()

        layout.addWidget(
            self.status_title
        )
        layout.addWidget(
            self.status_detail
        )
        layout.addWidget(
            self.progress
        )
        layout.addWidget(
            self.result_path_label
        )
        layout.addLayout(
            action_row
        )

        return panel

    def _create_history_panel(
        self,
    ) -> QGroupBox:
        panel = QGroupBox(
            'Conversões recentes'
        )

        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        heading_row = QHBoxLayout()

        hint = QLabel(
            'Clique duas vezes em um resultado para abri-lo.'
        )
        hint.setObjectName("mutedText")

        self.history_open_button = QPushButton(
            'Abrir selecionado'
        )
        self.history_folder_button = QPushButton(
            'Abrir pasta'
        )
        self.clear_history_button = QPushButton(
            'Limpar histórico'
        )

        self.history_open_button.setEnabled(False)
        self.history_folder_button.setEnabled(False)

        self.history_open_button.clicked.connect(
            self._open_selected_history_file
        )
        self.history_folder_button.clicked.connect(
            self._open_selected_history_folder
        )
        self.clear_history_button.clicked.connect(
            self._clear_history
        )

        heading_row.addWidget(hint)
        heading_row.addWidget(
            HelpIconButton(
                'Histórico de conversões',
                (
                    '<p>Exibe as conversões concluídas recentemente e permite abrir '
                    'o resultado ou a pasta correspondente.</p>'
                    '<p><b>Limpar histórico</b> remove apenas os registros desta lista; '
                    'os arquivos convertidos continuam no disco.</p>'
                ),
            )
        )
        heading_row.addStretch()
        heading_row.addWidget(
            self.history_open_button
        )
        heading_row.addWidget(
            self.history_folder_button
        )
        heading_row.addWidget(
            self.clear_history_button
        )

        self.empty_history_state = EmptyState(
            'Nenhuma conversão recente',
            (
                'Escolha um arquivo DOCX ou PDF. As conversões concluídas '
                'aparecerão aqui para acesso rápido.'
            ),
            icon='⇄',
        )
        self.empty_history_state.setMinimumHeight(170)
        self.empty_history_state.add_action(
            'Selecionar arquivo',
            self._browse_source,
            primary=True,
        )

        self.history_table = QTableWidget(
            0,
            4,
        )
        self.history_table.setObjectName(
            "conversionHistoryTable"
        )
        self.history_table.setHorizontalHeaderLabels(
            [
                'Origem',
                'Arquivo convertido',
                'Tipo',
                'Concluído em',
            ]
        )
        self.history_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.history_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.history_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.history_table.setAlternatingRowColors(
            True
        )
        self.history_table.setShowGrid(False)
        self.history_table.verticalHeader().setVisible(
            False
        )
        self.history_table.setMinimumHeight(
            210
        )

        header = (
            self.history_table.horizontalHeader()
        )
        header.setSectionResizeMode(
            0,
            QHeaderView.ResizeMode.Stretch,
        )
        header.setSectionResizeMode(
            1,
            QHeaderView.ResizeMode.Stretch,
        )
        header.setSectionResizeMode(
            2,
            QHeaderView.ResizeMode.ResizeToContents,
        )
        header.setSectionResizeMode(
            3,
            QHeaderView.ResizeMode.ResizeToContents,
        )

        self.history_table.itemSelectionChanged.connect(
            self._update_history_buttons
        )
        self.history_table.cellDoubleClicked.connect(
            lambda _row, _column: (
                self._open_selected_history_file()
            )
        )

        layout.addLayout(
            heading_row
        )
        layout.addWidget(
            self.empty_history_state
        )
        layout.addWidget(
            self.history_table
        )

        return panel

    def focus_direction(
        self,
        direction: str,
    ) -> None:
        if direction not in self.DIRECTIONS:
            direction = "docx_to_pdf"

        self._set_direction(
            direction,
            clear_incompatible=True,
        )
        self.drop_zone.setFocus()

    def _set_direction(
        self,
        direction: str,
        *,
        clear_incompatible: bool,
    ) -> None:
        if direction not in self.DIRECTIONS:
            return

        self._direction = direction
        config = self.DIRECTIONS[direction]

        self.docx_mode_button.blockSignals(True)
        self.pdf_mode_button.blockSignals(True)

        self.docx_mode_button.setChecked(
            direction == "docx_to_pdf"
        )
        self.pdf_mode_button.setChecked(
            direction == "pdf_to_docx"
        )

        self.docx_mode_button.blockSignals(False)
        self.pdf_mode_button.blockSignals(False)

        source_suffix = str(
            config["source_suffix"]
        )
        self.drop_zone.set_expected_suffix(
            source_suffix
        )
        self.convert_button.setText(
            str(config["button"])
        )

        if (
            clear_incompatible
            and self._selected_source is not None
            and self._selected_source.suffix.lower()
            != source_suffix
        ):
            self._clear_selected_source()
        elif self._selected_source is not None:
            self._update_selected_file_panel()

    def _browse_source(self) -> None:
        config = self.DIRECTIONS[
            self._direction
        ]

        filename, _ = QFileDialog.getOpenFileName(
            self,
            'Selecionar arquivo para conversão',
            "",
            str(config["filter"]),
        )

        if filename:
            self._select_source(filename)

    def _select_source(
        self,
        filename: str,
    ) -> None:
        if self._busy:
            return

        source = Path(filename)

        if not source.exists():
            QMessageBox.warning(
                self,
                'Arquivo não encontrado',
                "O arquivo selecionado não foi encontrado. "
                "Ele pode ter sido movido ou excluído.",
            )
            return

        if not source.is_file():
            QMessageBox.warning(
                self,
                'Seleção inválida',
                'Selecione um arquivo DOCX ou PDF.',
            )
            return

        suffix = source.suffix.lower()

        if suffix == ".docx":
            direction = "docx_to_pdf"
        elif suffix == ".pdf":
            direction = "pdf_to_docx"
        else:
            QMessageBox.warning(
                self,
                'Arquivo não compatível',
                'Somente arquivos DOCX e PDF podem ser convertidos.',
            )
            return

        self._set_direction(
            direction,
            clear_incompatible=False,
        )
        self._selected_source = source
        self._last_output = None
        self._active_destination = None

        self._update_selected_file_panel()
        self.selected_panel.setVisible(True)
        self._show_ready_state(
            detail=(
                "O arquivo está pronto. Confira o nome automático da saída "
                "e inicie a conversão."
            )
        )

    def _update_selected_file_panel(
        self,
    ) -> None:
        source = self._selected_source

        if source is None:
            return

        config = self.DIRECTIONS[
            self._direction
        ]
        destination = self._automatic_destination(
            source,
            str(config["destination_suffix"]),
        )

        self.source_name_label.setText(
            source.name
        )
        self.source_path_label.setText(
            str(source.parent)
        )
        self.direction_label.setText(
            "Conversão: "
            f"{config['label']}"
        )
        self.output_preview_label.setText(
            "Saída automática: "
            f"{destination.name}\n"
            f"{destination.parent}"
        )

    def _automatic_destination(
        self,
        source: Path,
        destination_suffix: str,
        *,
        prompt: bool = False,
    ) -> Path | None:
        destination = source.with_suffix(
            destination_suffix
        )

        if not destination.exists():
            return destination

        mode = str(
            self.settings.value(
                "output/conflict",
                "rename",
            )
        )

        if mode == "replace":
            return destination

        if mode == "timestamp":
            stamp = datetime.now().strftime(
                "%Y%m%d-%H%M%S"
            )
            return source.with_name(
                f"{source.stem}_{stamp}"
                f"{destination_suffix}"
            )

        if mode == "ask":
            if not prompt:
                return destination
            answer = QMessageBox.question(
                self,
                'O arquivo convertido já existe',
                "Substituir o arquivo convertido existente?\n\n"
                f"{destination}",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                return destination
            if answer == QMessageBox.StandardButton.Cancel:
                return None

        converted = source.with_name(
            f"{source.stem}_converted"
            f"{destination_suffix}"
        )

        if not converted.exists():
            return converted

        counter = 2

        while True:
            candidate = source.with_name(
                f"{source.stem}_converted_{counter}"
                f"{destination_suffix}"
            )

            if not candidate.exists():
                return candidate

            counter += 1

    def _start_conversion(self) -> None:
        if self._busy:
            return

        source = self._selected_source

        if source is None:
            QMessageBox.warning(
                self,
                'Selecionar arquivo',
                'Primeiro, selecione ou arraste um arquivo DOCX ou PDF.',
            )
            return

        if not source.exists():
            self._show_error_state(
                "O arquivo selecionado não está mais disponível. "
                "Selecione-o novamente."
            )
            return

        config = self.DIRECTIONS[
            self._direction
        ]
        expected_suffix = str(
            config["source_suffix"]
        )

        if source.suffix.lower() != expected_suffix:
            self._show_error_state(
                "O arquivo selecionado não corresponde "
                "ao tipo de conversão escolhido."
            )
            return

        destination = self._automatic_destination(
            source,
            str(config["destination_suffix"]),
            prompt=True,
        )
        if destination is None:
            self._show_ready_state(
                detail='Conversão cancelada.'
            )
            return
        self._active_destination = destination

        self._set_busy(True)
        self._progress_stage_index = 0
        self._set_status_state("busy")
        self.status_title.setText(
            'Convertendo documento'
        )
        self.status_detail.setText(
            str(config["stages"][0])
        )
        self.result_path_label.setVisible(False)
        self._set_result_buttons_visible(False)
        self.progress.setVisible(True)
        self._progress_timer.start()

        task = _ConversionTask(
            direction=self._direction,
            source=source,
            destination=destination,
        )
        task.signals.finished.connect(
            self._conversion_finished
        )
        self._thread_pool.start(task)

    def _advance_progress_stage(self) -> None:
        if not self._busy:
            self._progress_timer.stop()
            return

        stages = list(
            self.DIRECTIONS[
                self._direction
            ]["stages"]
        )

        if not stages:
            return

        self._progress_stage_index = (
            self._progress_stage_index + 1
        ) % len(stages)
        self.status_detail.setText(
            str(
                stages[
                    self._progress_stage_index
                ]
            )
        )

    @Slot(bool, str, str, str, str)
    def _conversion_finished(
        self,
        success: bool,
        direction: str,
        source: str,
        output: str,
        message: str,
    ) -> None:
        self._progress_timer.stop()
        self._set_busy(False)

        if not success:
            friendly = self._friendly_error(
                message,
                Path(source),
            )
            self._show_error_state(
                friendly,
                technical_message=message,
            )
            return

        self._last_output = Path(output)
        self._active_destination = None

        self._set_status_state("success")
        self.status_title.setText(
            'Conversão concluída'
        )
        self.status_detail.setText(
            f"Criado: {self._last_output.name}"
        )
        self.result_path_label.setText(
            str(self._last_output)
        )
        self.result_path_label.setVisible(True)
        self.progress.setVisible(False)
        self._set_result_buttons_visible(True)

        if message.strip():
            self.status_detail.setText(
                f"Criado: {self._last_output.name}. "
                "O conversor foi concluído com observações."
            )
            self.status_detail.setToolTip(
                message.strip()
            )
        else:
            self.status_detail.setToolTip("")

        self._add_history_record(
            direction=direction,
            source=Path(source),
            output=self._last_output,
        )

        self.conversion_completed.emit(
            direction,
            source,
            output,
        )

    def _set_busy(
        self,
        busy: bool,
    ) -> None:
        self._busy = busy

        self.drop_zone.set_busy(busy)
        self.docx_mode_button.setEnabled(
            not busy
        )
        self.pdf_mode_button.setEnabled(
            not busy
        )
        self.convert_button.setEnabled(
            not busy
        )
        self.change_source_button.setEnabled(
            not busy
        )

    def _show_ready_state(
        self,
        *,
        detail: str | None = None,
    ) -> None:
        self._set_status_state("ready")
        self.status_title.setText(
            'Pronto para converter'
        )
        self.status_detail.setText(
            detail
            or 'Selecione ou arraste um arquivo para começar.'
        )
        self.status_detail.setToolTip("")
        self.progress.setVisible(False)
        self.result_path_label.setVisible(False)
        self._set_result_buttons_visible(False)

    def _show_error_state(
        self,
        message: str,
        *,
        technical_message: str = "",
    ) -> None:
        self._set_status_state("error")
        self.status_title.setText(
            'Falha na conversão'
        )
        self.status_detail.setText(
            message
        )
        self.status_detail.setToolTip(
            technical_message
        )
        self.progress.setVisible(False)
        self.result_path_label.setVisible(False)
        self.open_output_button.setVisible(False)
        self.open_folder_button.setVisible(False)
        self.convert_another_button.setText(
            'Selecionar outro arquivo'
        )
        self.convert_another_button.setVisible(
            True
        )

    def _set_status_state(
        self,
        state: str,
    ) -> None:
        self.status_panel.setProperty(
            "statusState",
            state,
        )
        self.status_panel.style().unpolish(
            self.status_panel
        )
        self.status_panel.style().polish(
            self.status_panel
        )
        self.status_panel.update()

    def _set_result_buttons_visible(
        self,
        visible: bool,
    ) -> None:
        self.open_output_button.setVisible(
            visible
        )
        self.open_folder_button.setVisible(
            visible
        )
        self.convert_another_button.setText(
            'Converter outro'
        )
        self.convert_another_button.setVisible(
            visible
        )

    def _reset_workflow(self) -> None:
        if self._busy:
            return

        self._clear_selected_source()
        self._show_ready_state()
        self.drop_zone.setFocus()

    def _clear_selected_source(self) -> None:
        self._selected_source = None
        self._active_destination = None
        self.selected_panel.setVisible(False)

    @staticmethod
    def _friendly_error(
        message: str,
        source: Path,
    ) -> str:
        lowered = message.casefold()

        if (
            "permission" in lowered
            or "access denied" in lowered
            or "being used" in lowered
            or "in use" in lowered
        ):
            return (
                "Não foi possível acessar o arquivo. Feche-o em outros aplicativos, "
                "verifique as permissões da pasta e tente novamente."
            )

        if (
            "password" in lowered
            or "encrypted" in lowered
            or "protected" in lowered
        ):
            return (
                "O arquivo parece estar protegido por senha ou criptografado. "
                "Remova a proteção antes de convertê-lo."
            )

        if (
            "corrupt" in lowered
            or "damaged" in lowered
            or "invalid" in lowered
            or "cannot open" in lowered
            or "could not open" in lowered
        ):
            return (
                f"Não foi possível ler {source.name}. Verifique se o arquivo abre "
                "normalmente e não está danificado."
            )

        if (
            "not found" in lowered
            or "no such file" in lowered
        ):
            return (
                "O arquivo de origem não está mais disponível. "
                "Ele pode ter sido movido ou excluído."
            )

        return (
            "Não foi possível converter o arquivo. Verifique se ele abre normalmente "
            "e tente novamente. O erro original aparece ao passar o mouse sobre esta mensagem."
        )

    def _open_last_output(self) -> None:
        output = self._last_output

        if output is None:
            return

        self._open_file(output)

    def _open_last_folder(self) -> None:
        output = self._last_output

        if output is None:
            return

        self._open_folder(
            output.parent
        )

    def _open_file(
        self,
        path: Path,
    ) -> None:
        try:
            open_file(path)
        except SystemOpenError as exc:
            QMessageBox.warning(
                self,
                'Não foi possível abrir o arquivo',
                str(exc),
            )

    def _open_folder(
        self,
        folder: Path,
    ) -> None:
        try:
            open_folder(folder)
        except SystemOpenError as exc:
            QMessageBox.warning(
                self,
                'Não foi possível abrir a pasta',
                str(exc),
            )

    def _load_history(
        self,
    ) -> list[dict[str, str]]:
        raw = self.settings.value(
            self.HISTORY_KEY,
            "[]",
        )

        if isinstance(raw, list):
            data: Any = raw
        else:
            try:
                data = json.loads(
                    str(raw or "[]")
                )
            except (
                TypeError,
                json.JSONDecodeError,
            ):
                data = []

        if not isinstance(data, list):
            return []

        history: list[dict[str, str]] = []

        for record in data:
            if not isinstance(record, dict):
                continue

            source = str(
                record.get("source", "")
            ).strip()
            output = str(
                record.get("output", "")
            ).strip()
            direction = str(
                record.get("direction", "")
            ).strip()
            completed_at = str(
                record.get("completed_at", "")
            ).strip()

            if (
                not source
                or not output
                or direction not in self.DIRECTIONS
            ):
                continue

            history.append(
                {
                    "source": source,
                    "output": output,
                    "direction": direction,
                    "completed_at": completed_at,
                }
            )

        return history[
            : self.HISTORY_LIMIT
        ]

    def _save_history(self) -> None:
        self.settings.setValue(
            self.HISTORY_KEY,
            json.dumps(
                self._history,
                ensure_ascii=False,
            ),
        )
        self.settings.sync()

    def _add_history_record(
        self,
        *,
        direction: str,
        source: Path,
        output: Path,
    ) -> None:
        output_key = str(
            output.resolve()
        ).casefold()

        self._history = [
            record
            for record in self._history
            if str(
                record.get("output", "")
            ).casefold()
            != output_key
        ]

        self._history.insert(
            0,
            {
                "source": str(source),
                "output": str(output),
                "direction": direction,
                "completed_at": datetime.now().isoformat(
                    timespec="seconds"
                ),
            },
        )

        self._history = self._history[
            : self.HISTORY_LIMIT
        ]
        self._save_history()
        self._refresh_history_table()

    def _refresh_history_table(self) -> None:
        self.history_table.setRowCount(0)

        for record in self._history:
            row = self.history_table.rowCount()
            self.history_table.insertRow(row)

            source = Path(
                record["source"]
            )
            output = Path(
                record["output"]
            )
            direction = record["direction"]

            values = [
                source.name,
                output.name,
                str(
                    self.DIRECTIONS[
                        direction
                    ]["label"]
                ),
                self._format_history_date(
                    record.get(
                        "completed_at",
                        "",
                    )
                ),
            ]

            for column, value in enumerate(values):
                item = QTableWidgetItem(
                    value
                )
                item.setToolTip(
                    str(
                        output
                        if column == 1
                        else source
                        if column == 0
                        else value
                    )
                )
                item.setData(
                    Qt.ItemDataRole.UserRole,
                    str(output),
                )
                self.history_table.setItem(
                    row,
                    column,
                    item,
                )

        has_history = bool(
            self._history
        )
        self.history_table.setVisible(
            has_history
        )
        self.empty_history_state.setVisible(
            not has_history
        )
        self.clear_history_button.setEnabled(
            has_history
        )

        if has_history:
            self.history_table.selectRow(0)

        self._update_history_buttons()

    @staticmethod
    def _format_history_date(
        value: str,
    ) -> str:
        if not value:
            return "—"

        try:
            parsed = datetime.fromisoformat(
                value
            )
        except ValueError:
            return value

        return parsed.strftime(
            "%Y-%m-%d %H:%M"
        )

    def _selected_history_output(
        self,
    ) -> Path | None:
        selected = (
            self.history_table.selectedItems()
        )

        if not selected:
            return None

        value = selected[0].data(
            Qt.ItemDataRole.UserRole
        )

        if not value:
            return None

        return Path(
            str(value)
        )

    def _update_history_buttons(self) -> None:
        selected = (
            self._selected_history_output()
            is not None
        )
        self.history_open_button.setEnabled(
            selected
        )
        self.history_folder_button.setEnabled(
            selected
        )

    def _open_selected_history_file(
        self,
    ) -> None:
        output = (
            self._selected_history_output()
        )

        if output is not None:
            self._open_file(output)

    def _open_selected_history_folder(
        self,
    ) -> None:
        output = (
            self._selected_history_output()
        )

        if output is not None:
            self._open_folder(
                output.parent
            )

    def _clear_history(self) -> None:
        if not self._history:
            return

        answer = QMessageBox.question(
            self,
            'Limpar histórico de conversões',
            "Remover todos os registros de conversão desta lista?\n\n"
            "Os arquivos convertidos não serão excluídos.",
        )

        if (
            answer
            != QMessageBox.StandardButton.Yes
        ):
            return

        self._history = []
        self._save_history()
        self._refresh_history_table()
