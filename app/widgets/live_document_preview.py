from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.docx_engine import (
    DocumentGenerationError,
    generate_docx,
)
from app.pdf_converter import (
    PdfConversionError,
    available_converter,
    convert_docx_to_pdf,
)

try:
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtPdfWidgets import QPdfView

    PDF_VIEW_AVAILABLE = True
except ImportError:
    QPdfDocument = None
    QPdfView = None
    PDF_VIEW_AVAILABLE = False


class _PreviewSignals(QObject):
    finished = Signal(
        int,
        object,
        str,
    )


class _PreviewRenderTask(QRunnable):
    """
    Generate and render one preview without blocking the interface.
    """

    def __init__(
        self,
        *,
        request_id: int,
        template_path: Path,
        values: dict[str, Any],
        request_folder: Path,
    ) -> None:
        super().__init__()

        self.request_id = request_id
        self.template_path = Path(
            template_path
        )
        self.values = dict(values)
        self.request_folder = Path(
            request_folder
        )
        self.signals = _PreviewSignals()

    @Slot()
    def run(self) -> None:
        preview_docx = (
            self.request_folder
            / "live-preview.docx"
        )
        preview_pdf = (
            self.request_folder
            / "live-preview.pdf"
        )

        com_initialized = False

        try:
            self.request_folder.mkdir(
                parents=True,
                exist_ok=True,
            )

            generate_docx(
                self.template_path,
                preview_docx,
                self.values,
            )

            # Microsoft Word conversion uses COM. Background threads must
            # initialize COM explicitly.
            if sys.platform.startswith(
                "win"
            ):
                try:
                    import pythoncom  # type: ignore

                    pythoncom.CoInitialize()
                    com_initialized = True
                except Exception:
                    com_initialized = False

            rendered_pdf = (
                convert_docx_to_pdf(
                    preview_docx,
                    preview_pdf,
                )
            )

            self.signals.finished.emit(
                self.request_id,
                rendered_pdf,
                "",
            )

        except (
            DocumentGenerationError,
            PdfConversionError,
        ) as exc:
            self.signals.finished.emit(
                self.request_id,
                None,
                str(exc),
            )

        except Exception as exc:
            self.signals.finished.emit(
                self.request_id,
                None,
                (
                    "The live preview could not "
                    f"be rendered: {exc}"
                ),
            )

        finally:
            if com_initialized:
                try:
                    import pythoncom  # type: ignore

                    pythoncom.CoUninitialize()
                except Exception:
                    pass


class LiveDocumentPreview(QFrame):
    """
    Embedded document preview for the Generate page.

    The preview refreshes after the user pauses typing. Rendering happens in a
    worker thread so the form remains responsive.
    """

    def __init__(
        self,
        parent=None,
    ) -> None:
        super().__init__(parent)

        self.setObjectName(
            "livePreviewPanel"
        )
        self.setMinimumWidth(420)

        self._template_name = ""
        self._template_path: Path | None = None
        self._latest_values: dict[
            str,
            Any,
        ] = {}

        self._request_id = 0
        self._busy = False
        self._pending = False
        self._current_pdf: Path | None = None

        self._temp_root = Path(
            tempfile.mkdtemp(
                prefix="docgen-live-preview-"
            )
        )

        self._thread_pool = (
            QThreadPool.globalInstance()
        )

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(
            True
        )
        self._refresh_timer.setInterval(
            1100
        )
        self._refresh_timer.timeout.connect(
            self.refresh_now
        )

        self._build_interface()

    def _build_interface(self) -> None:
        title = QLabel(
            "Live Document Preview"
        )
        title.setObjectName(
            "previewTitle"
        )

        self.status_label = QLabel(
            "Select a template to begin."
        )
        self.status_label.setObjectName(
            "previewStatus"
        )
        self.status_label.setWordWrap(True)

        title_row = QHBoxLayout()
        title_row.addWidget(title)
        title_row.addStretch()

        self.auto_checkbox = QCheckBox(
            "Auto"
        )
        self.auto_checkbox.setChecked(True)
        self.auto_checkbox.setToolTip(
            "Refresh after you pause typing."
        )
        self.auto_checkbox.toggled.connect(
            self._auto_changed
        )
        title_row.addWidget(
            self.auto_checkbox
        )

        self.refresh_button = QPushButton(
            "Refresh"
        )
        self.refresh_button.clicked.connect(
            self.refresh_now
        )
        title_row.addWidget(
            self.refresh_button
        )

        self.zoom_out_button = QPushButton(
            "−"
        )
        self.zoom_out_button.setFixedWidth(
            36
        )
        self.zoom_out_button.setToolTip(
            "Zoom out"
        )

        self.fit_width_button = QPushButton(
            "Fit Width"
        )

        self.fit_page_button = QPushButton(
            "Fit Page"
        )

        self.zoom_in_button = QPushButton(
            "+"
        )
        self.zoom_in_button.setFixedWidth(
            36
        )
        self.zoom_in_button.setToolTip(
            "Zoom in"
        )

        self.page_count_label = QLabel(
            ""
        )
        self.page_count_label.setObjectName(
            "mutedText"
        )

        preview_controls = QHBoxLayout()
        preview_controls.addWidget(
            self.zoom_out_button
        )
        preview_controls.addWidget(
            self.fit_width_button
        )
        preview_controls.addWidget(
            self.fit_page_button
        )
        preview_controls.addWidget(
            self.zoom_in_button
        )
        preview_controls.addStretch()
        preview_controls.addWidget(
            self.page_count_label
        )

        self.stack = QStackedWidget()

        self.message_page = QWidget()
        message_layout = QVBoxLayout(
            self.message_page
        )
        message_layout.setContentsMargins(
            12,
            12,
            12,
            12,
        )

        self.message_label = QLabel(
            "The preview will appear here."
        )
        self.message_label.setObjectName(
            "livePreviewMessage"
        )
        self.message_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        self.message_label.setWordWrap(True)
        message_layout.addWidget(
            self.message_label,
            1,
        )

        self.stack.addWidget(
            self.message_page
        )

        self.pdf_page = QWidget()
        pdf_layout = QVBoxLayout(
            self.pdf_page
        )
        pdf_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        self.pdf_document = None
        self.pdf_view = None

        if PDF_VIEW_AVAILABLE:
            self.pdf_document = QPdfDocument(
                self
            )
            self.pdf_view = QPdfView(
                self.pdf_page
            )
            self.pdf_view.setDocument(
                self.pdf_document
            )
            self.pdf_view.setPageMode(
                QPdfView.PageMode.MultiPage
            )
            self.pdf_view.setZoomMode(
                QPdfView.ZoomMode.FitToWidth
            )
            self.pdf_document.pageCountChanged.connect(
                self._update_page_count
            )
            pdf_layout.addWidget(
                self.pdf_view,
                1,
            )

            self.zoom_out_button.clicked.connect(
                lambda: self._change_zoom(
                    0.85
                )
            )
            self.zoom_in_button.clicked.connect(
                lambda: self._change_zoom(
                    1.15
                )
            )
            self.fit_width_button.clicked.connect(
                lambda: self.pdf_view.setZoomMode(
                    QPdfView.ZoomMode.FitToWidth
                )
            )
            self.fit_page_button.clicked.connect(
                lambda: self.pdf_view.setZoomMode(
                    QPdfView.ZoomMode.FitInView
                )
            )
        else:
            unavailable = QLabel(
                "This PySide6 installation does not "
                "include QtPdf/QtPdfWidgets."
            )
            unavailable.setAlignment(
                Qt.AlignmentFlag.AlignCenter
            )
            unavailable.setWordWrap(True)
            pdf_layout.addWidget(
                unavailable,
                1,
            )

        self.stack.addWidget(
            self.pdf_page
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            12,
            12,
            12,
            12,
        )
        layout.setSpacing(9)
        layout.addLayout(title_row)
        layout.addWidget(
            self.status_label
        )
        layout.addLayout(
            preview_controls
        )
        layout.addWidget(
            self.stack,
            1,
        )

        self._set_preview_controls_enabled(
            False
        )

    def set_template(
        self,
        *,
        template_name: str,
        template_path: Path,
        values: dict[str, Any],
    ) -> None:
        self._template_name = str(
            template_name
        )
        self._template_path = Path(
            template_path
        )
        self._latest_values = dict(
            values
        )

        self.status_label.setText(
            f"Preparing {self._template_name}…"
        )
        self.message_label.setText(
            "The preview will update after "
            "you pause typing."
        )
        self.stack.setCurrentWidget(
            self.message_page
        )

        self.schedule_preview(
            values,
            immediate=True,
        )

    def clear_preview(self) -> None:
        self._refresh_timer.stop()
        self._template_name = ""
        self._template_path = None
        self._latest_values = {}
        self._pending = False

        self.status_label.setText(
            "Select a template to begin."
        )
        self.message_label.setText(
            "The preview will appear here."
        )
        self.page_count_label.clear()
        self.stack.setCurrentWidget(
            self.message_page
        )
        self._set_preview_controls_enabled(
            False
        )

    def schedule_preview(
        self,
        values: dict[str, Any],
        *,
        immediate: bool = False,
    ) -> None:
        self._latest_values = dict(values)

        if not self.auto_checkbox.isChecked():
            self.status_label.setText(
                "Live refresh is paused."
            )
            return

        self.status_label.setText(
            "Waiting for you to pause typing…"
        )

        self._refresh_timer.start(
            80 if immediate else 1100
        )

    @Slot()
    def refresh_now(self) -> None:
        self._refresh_timer.stop()

        if self._template_path is None:
            self.clear_preview()
            return

        converter = available_converter()

        if converter is None:
            self._show_error(
                "A real document-page preview needs "
                "Microsoft Word with pywin32 or "
                "LibreOffice/soffice installed locally."
            )
            return

        if not PDF_VIEW_AVAILABLE:
            self._show_error(
                "The local converter is available, but "
                "this PySide6 installation does not "
                "include QtPdf/QtPdfWidgets."
            )
            return

        if self._busy:
            self._pending = True
            self.status_label.setText(
                "A newer preview is waiting…"
            )
            return

        self._busy = True
        self._pending = False
        self._request_id += 1

        request_id = self._request_id
        request_folder = (
            self._temp_root
            / f"request-{request_id}"
        )

        self.refresh_button.setEnabled(False)
        self.status_label.setText(
            f"Rendering with {converter}…"
        )

        task = _PreviewRenderTask(
            request_id=request_id,
            template_path=self._template_path,
            values=self._latest_values,
            request_folder=request_folder,
        )
        task.signals.finished.connect(
            self._render_finished
        )
        self._thread_pool.start(task)

    @Slot(
        int,
        object,
        str,
    )
    def _render_finished(
        self,
        request_id: int,
        pdf_path: object,
        error: str,
    ) -> None:
        self._busy = False
        self.refresh_button.setEnabled(True)

        if request_id != self._request_id:
            return

        if error:
            self._show_error(error)
        elif pdf_path:
            self._load_pdf(
                Path(str(pdf_path))
            )
        else:
            self._show_error(
                "The preview did not create a PDF."
            )

        if self._pending:
            self._pending = False
            self._refresh_timer.start(120)

    def _load_pdf(
        self,
        pdf_path: Path,
    ) -> None:
        if (
            self.pdf_document is None
            or self.pdf_view is None
        ):
            self._show_error(
                "QtPdf is not available."
            )
            return

        try:
            self.pdf_document.close()
        except Exception:
            pass

        self._current_pdf = pdf_path
        self.pdf_document.load(
            str(pdf_path)
        )
        self.pdf_view.setZoomMode(
            QPdfView.ZoomMode.FitToWidth
        )
        self.stack.setCurrentWidget(
            self.pdf_page
        )
        self.status_label.setText(
            "Preview updated. Changes refresh "
            "after you pause typing."
        )
        self._set_preview_controls_enabled(
            True
        )

    def _show_error(
        self,
        message: str,
    ) -> None:
        self.message_label.setText(
            message
        )
        self.status_label.setText(
            "Preview unavailable"
        )
        self.page_count_label.clear()
        self.stack.setCurrentWidget(
            self.message_page
        )
        self._set_preview_controls_enabled(
            False
        )

    def _auto_changed(
        self,
        enabled: bool,
    ) -> None:
        if enabled:
            self.schedule_preview(
                self._latest_values,
                immediate=True,
            )
        else:
            self._refresh_timer.stop()
            self.status_label.setText(
                "Live refresh is paused. "
                "Use Refresh to update manually."
            )

    def _change_zoom(
        self,
        multiplier: float,
    ) -> None:
        if self.pdf_view is None:
            return

        current = self.pdf_view.zoomFactor()

        if current <= 0:
            current = 1.0

        next_factor = max(
            0.25,
            min(
                current * multiplier,
                4.0,
            ),
        )

        self.pdf_view.setZoomMode(
            QPdfView.ZoomMode.Custom
        )
        self.pdf_view.setZoomFactor(
            next_factor
        )

    @Slot(int)
    def _update_page_count(
        self,
        page_count: int,
    ) -> None:
        if page_count <= 0:
            self.page_count_label.setText(
                "Loading…"
            )
            return

        self.page_count_label.setText(
            f"{page_count} page"
            if page_count == 1
            else f"{page_count} pages"
        )

    def _set_preview_controls_enabled(
        self,
        enabled: bool,
    ) -> None:
        for button in (
            self.zoom_out_button,
            self.fit_width_button,
            self.fit_page_button,
            self.zoom_in_button,
        ):
            button.setEnabled(enabled)

    def cleanup(self) -> None:
        self._refresh_timer.stop()

        try:
            if self.pdf_document is not None:
                self.pdf_document.close()
        except Exception:
            pass

        shutil.rmtree(
            self._temp_root,
            ignore_errors=True,
        )

    def closeEvent(self, event) -> None:
        self.cleanup()
        super().closeEvent(event)
