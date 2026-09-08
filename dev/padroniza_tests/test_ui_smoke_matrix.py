from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtWidgets import QApplication, QDialog, QToolButton, QWidget

from app.repositories.favorites import FavoriteStore
from app.repositories.field_library import FieldLibraryStore
from app.repositories.local_data import LocalDataStore
from app.repositories.templates import TemplateRepository
from app.ui.dialogs.automatic_detection_dialog import AutomaticDetectionDialog
from app.ui.dialogs.backup_contents_dialog import BackupContentsDialog
from app.ui.dialogs.diagnostics_dialog import DiagnosticsDialog
from app.ui.dialogs.field_library_dialog import FieldLibraryDialog
from app.ui.dialogs.filename_builder_dialog import FilenameBuilderDialog
from app.ui.dialogs.global_search_dialog import GlobalSearchDialog
from app.ui.dialogs.profile_manager_dialog import ProfileManagerDialog
from app.ui.dialogs.version_history_dialog import VersionHistoryDialog
from app.ui.main_window import MainWindow
from app.ui.template_manager.template_editor_dialog import TemplateEditorDialog
from app.ui.template_manager.template_manager_dialog import TemplateManagerDialog
from app.ui.theme import ThemeManager
from app.ui.widgets.document_form import DocumentForm
from app.ui.widgets.field_layout_editor import FieldLayoutEditor
from app.ui.widgets.file_converter_page import FileConverterPage
from app.ui.widgets.home_page import HomePage
from app.ui.widgets.searchable_dropdown import SearchableDropdown
from app.ui.widgets.repeatable_table import RepeatableTableWidget
from app.ui.widgets.sidebar import Sidebar
from app.ui.widgets.template_header import TemplateHeader
from app.ui.widgets.tutorial_page import TutorialPage


@pytest.fixture(scope="module")
def qt_app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def ui_storage(tmp_path: Path) -> Path:
    for folder in ("templates", "data", "backups", "output"):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)

    # Keep all QSettings writes inside the temporary test tree.  This prevents
    # an offscreen quality run from changing the developer's actual Padroniza
    # preferences in the Windows registry.
    settings_root = tmp_path / "data" / "qsettings"
    settings_root.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(settings_root),
    )
    return tmp_path


def _close(widget: QWidget, app: QApplication) -> None:
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_all_primary_pages_navigate_without_constructing_errors(
    qt_app: QApplication,
    ui_storage: Path,
) -> None:
    source_root = Path(__file__).resolve().parents[1]
    settings = QSettings(
        str(ui_storage / "data" / "ui-smoke.ini"),
        QSettings.Format.IniFormat,
    )
    settings.clear()
    favorite_store = FavoriteStore(settings)

    theme = ThemeManager(app=qt_app, project_root=source_root)
    theme.apply_theme("light")
    window = MainWindow(
        project_root=ui_storage,
        theme_manager=theme,
        default_output_dir=ui_storage / "output",
    )
    # Keep the smoke test isolated from the machine's native QSettings.
    window.favorite_store = favorite_store

    for target in (
        "home",
        "generate",
        "templates",
        "recent",
        "favorites",
        "archive",
        "settings",
        "converter",
        "tutorial",
    ):
        window._navigate_to_target(target)
        qt_app.processEvents()
        expected = {
            "home": window.home_page,
            "generate": window.generate_page,
            "templates": window.templates_page,
            "recent": window.recent_page,
            "favorites": window.favorites_page,
            "archive": window.archive_page,
            "settings": window.settings_page,
            "converter": window.converter_page,
            "tutorial": window.tutorial_page,
        }[target]
        assert window.pages.currentWidget() is expected

    window._show_converter_page("docx_to_pdf")
    window._show_converter_page("pdf_to_docx")
    window._refresh_home_page()
    window._refresh_recent_page()
    window._refresh_favorites_page()
    window._refresh_archive_page()
    window._refresh_audit_page()
    _close(window, qt_app)

    # Reopening catches cleanup/singleton assumptions that only fail on the
    # second application window in a real desktop session.
    reopened = MainWindow(
        project_root=ui_storage,
        theme_manager=theme,
        default_output_dir=ui_storage / "output",
    )
    assert "Padroniza" in reopened.windowTitle()
    _close(reopened, qt_app)


def test_dialog_and_widget_constructor_matrix(
    qt_app: QApplication,
    ui_storage: Path,
) -> None:
    repository = TemplateRepository(ui_storage / "templates")
    local_store = LocalDataStore(ui_storage / "data")
    field_library = FieldLibraryStore(ui_storage / "data")
    settings = QSettings(
        str(ui_storage / "data" / "favorites.ini"),
        QSettings.Format.IniFormat,
    )
    favorite_store = FavoriteStore(settings)

    candidate = {
        "candidate_id": "candidate_0001",
        "field_id": "auto.nome",
        "label": "Nome",
        "type": "text",
        "confidence": 0.95,
        "source": "inline_placeholder",
        "preview": "Nome: ______",
        "selected": True,
        "location": {"kind": "paragraph", "paragraph": 0},
    }
    report = {
        "issues": [
            {
                "severity": "warning",
                "code": "smoke.warning",
                "message": "Aviso de teste",
                "field_id": "auto.nome",
                "locations": ["Parágrafo 1"],
            }
        ],
        "blocking_count": 0,
        "warning_count": 1,
    }

    widgets: list[QWidget] = [
        AutomaticDetectionDialog([candidate]),
        BackupContentsDialog({"metadata": {"format": "Padroniza"}, "entries": []}),
        DiagnosticsDialog("Diagnóstico", "Aviso de teste", report=report),
        FieldLibraryDialog(field_library),
        FilenameBuilderDialog("{{template.name}}.docx"),
        GlobalSearchDialog([]),
        ProfileManagerDialog(local_store),
        VersionHistoryDialog(repository, "missing-template"),
        TemplateManagerDialog(ui_storage / "templates", favorite_store=favorite_store),
        TemplateEditorDialog(repository),  # "Novo modelo" constructor path.
        DocumentForm(),
        FieldLayoutEditor(),
        FileConverterPage(),
        HomePage(),
        SearchableDropdown(["Opção A", "Opção B"]),
        Sidebar(),
        TemplateHeader(),
        TutorialPage(),
    ]

    # Exercise the assisted-detection review filters/details introduced for the
    # user-facing review workflow.
    detection_dialog = next(
        widget for widget in widgets if isinstance(widget, AutomaticDetectionDialog)
    )
    detection_dialog.search_input.setText("nome")
    detection_dialog.confidence_filter.setCurrentIndex(1)
    detection_dialog.review_filter.setCurrentIndex(0)
    detection_dialog.type_filter.setCurrentIndex(0)
    detection_dialog._apply_filters()
    assert detection_dialog.table.isRowHidden(0) is False
    detection_dialog.table.selectRow(0)
    detection_dialog._update_details()
    assert "Nome" in detection_dialog.details_text.toPlainText()
    assert detection_dialog.table.isColumnHidden(2) is True
    assert detection_dialog.table.isColumnHidden(3) is True
    detection_dialog.technical_details_button.setChecked(True)
    assert detection_dialog.table.isColumnHidden(2) is False
    assert detection_dialog.table.isColumnHidden(3) is False

    # Exercise live template-field validation/status without touching a real
    # document. This catches broken table-column assumptions and filter wiring.
    editor = next(widget for widget in widgets if isinstance(widget, TemplateEditorDialog))
    # New and existing models intentionally share the same guided authoring flow.
    assert editor._creation_flow is True
    assert editor._creation_step == 0
    assert editor.fields_group.isHidden() is True
    assert editor.output_group.isHidden() is True
    editor._set_creation_step(1)
    assert editor.fields_group.isHidden() is False
    assert editor.fields_tabs.currentIndex() == 0
    assert editor.fields_tabs.tabBar().isHidden() is True
    assert editor.fields_table.isColumnHidden(0) is True
    editor.creation_advanced_button.setChecked(True)
    assert editor.simple_fields_checkbox.isHidden() is False
    editor.simple_fields_checkbox.setChecked(True)
    assert editor.fields_table.isColumnHidden(0) is False
    editor._set_creation_step(3)
    assert editor.fields_tabs.currentIndex() == 2
    assert editor.output_group.isHidden() is False
    editor.creation_advanced_button.setChecked(False)
    assert editor.output_group.isHidden() is True

    editor._load_fields_into_table(
        [
            {"id": "cliente.nome", "label": "Nome", "type": "text"},
            {"id": "tipo", "label": "Tipo", "type": "dropdown", "options": ["Única"]},
        ]
    )
    editor._refresh_field_validation()
    assert editor.fields_table.item(0, 11).text() == "OK"
    assert editor.fields_table.item(1, 11).data(Qt.ItemDataRole.UserRole) == "error"
    editor.field_status_filter.setCurrentIndex(editor.field_status_filter.findData("error"))
    editor._apply_field_filters()
    assert editor.fields_table.isRowHidden(0) is True
    assert editor.fields_table.isRowHidden(1) is False
    editor.field_status_filter.setCurrentIndex(editor.field_status_filter.findData("all"))
    editor._add_empty_field()
    editor._refresh_field_validation()
    blank_row = editor.fields_table.rowCount() - 1
    assert editor.fields_table.item(blank_row, 11).data(Qt.ItemDataRole.UserRole) == "error"
    editor._refresh_form_preview()
    editor.form_preview.load_sample_data()

    # Exercise the real form widget factory rather than merely constructing an
    # empty DocumentForm.
    document_form = next(widget for widget in widgets if isinstance(widget, DocumentForm))
    document_form.set_fields(
        [
            {"id": "nome", "label": "Nome", "type": "text", "required": True},
            {"id": "data", "label": "Data", "type": "date"},
            {"id": "ativo", "label": "Ativo", "type": "checkbox"},
            {
                "id": "tipo",
                "label": "Tipo",
                "type": "dropdown",
                "options": ["A", "B"],
            },
            {
                "id": "auto.unidade_gestora",
                "label": "Unidade Gestora",
                "type": "dropdown",
                "required": True,
                "options": ["Unidade A", "Unidade B"],
                "detection_source": "automatic",
            },
            {
                "id": "grade.nome",
                "label": "Nome na grade",
                "type": "text",
                "layout": "form_grid",
                "layout_group": "smoke-grid",
                "layout_row": "row_0",
                "layout_grid_columns": 2,
                "layout_column_index": 0,
            },
            {
                "id": "grade.valor",
                "label": "Valor na grade",
                "type": "text",
                "layout": "form_grid",
                "layout_group": "smoke-grid",
                "layout_row": "row_0",
                "layout_grid_columns": 2,
                "layout_column_index": 1,
            },
        ]
    )
    document_form.resize(960, 640)
    document_form.show()
    qt_app.processEvents()
    assert document_form.focus_field("nome") is not None

    # Generated fields use one visual shell: the dropdown consumes the field
    # width and the assisted-detection action stays directly above the editor
    # instead of floating at the far edge of a wide grid cell.
    assisted_editor = document_form.field_widgets["auto.unidade_gestora"]
    assert isinstance(assisted_editor, SearchableDropdown)
    assisted_card = document_form.field_containers["auto.unidade_gestora"]
    correction = assisted_card.findChild(QToolButton, "fieldCorrectionButton")
    assert correction is not None
    assert correction.text() == "Ajustar campo"
    correction_pos = correction.mapTo(assisted_card, QPoint(0, 0))
    editor_pos = assisted_editor.mapTo(assisted_card, QPoint(0, 0))
    assert correction_pos.x() <= 24
    assert correction_pos.y() < editor_pos.y()
    assert assisted_editor.button.width() >= assisted_editor.width() - 4

    for widget in widgets:
        assert widget.windowTitle() is not None
        _close(widget, qt_app)


def test_template_manager_new_model_action_opens_editor(
    qt_app: QApplication,
    ui_storage: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real ``Novo Modelo`` click path without blocking modally."""

    manager = TemplateManagerDialog(ui_storage / "templates")
    monkeypatch.setattr(
        TemplateEditorDialog,
        "exec",
        lambda self: QDialog.DialogCode.Rejected,
    )
    manager._create_template()
    _close(manager, qt_app)


def test_existing_template_editor_constructor(
    qt_app: QApplication,
    ui_storage: Path,
) -> None:
    """Exercise the separate Editar Modelo constructor path with real data."""

    source_root = Path(__file__).resolve().parents[1]
    bundled = next(
        path
        for path in sorted((source_root / "templates").iterdir())
        if path.is_dir() and (path / "template.json").exists()
    )
    destination = ui_storage / "templates" / bundled.name
    shutil.copytree(bundled, destination)

    repository = TemplateRepository(ui_storage / "templates")
    summary = repository.list_templates()[0]
    template_id = str(summary["id"])
    editor = TemplateEditorDialog(repository, template_id)
    assert editor.template_id == template_id
    assert editor._creation_flow is True
    assert editor._editing_existing is True
    assert editor._creation_has_scanned is True
    assert editor.fields_tabs.tabBar().isHidden() is True
    assert editor.selected_docx is not None
    _close(editor, qt_app)


def test_structural_repeatable_table_renders_as_one_grid(
    qt_app: QApplication,
) -> None:
    widget = RepeatableTableWidget(
        {
            "id": "auto.quantidade_a_ser_contratada",
            "label": "Quantidade a ser contratada",
            "type": "repeatable_table",
            "minimum_rows": 1,
            "columns": [
                {"id": "item", "label": "Item", "type": "auto_number"},
                {"id": "descricao", "label": "Descrição", "type": "multiline", "required": True},
                {"id": "und", "label": "UND", "type": "text", "required": True},
                {"id": "quantidade_2023", "label": "Quantidade — 2023", "group_label": "Quantidade", "type": "integer", "required": True},
                {"id": "quantidade_2024", "label": "Quantidade — 2024", "group_label": "Quantidade", "type": "integer", "required": True},
                {"id": "quantidade_2025", "label": "Quantidade — 2025", "group_label": "Quantidade", "type": "integer", "required": True},
                {"id": "quantidade_solicitada", "label": "Quantidade Solicitada", "type": "integer", "required": True},
                {"id": "consta_no_pca", "label": "Consta no PCA para 2026?", "type": "dropdown", "options": ["SIM", "NÃO"], "required": True},
                {"id": "justificativa", "label": "Justificativa se for o caso", "type": "multiline", "required": False},
            ],
        }
    )
    widget.resize(1200, 320)
    widget.show()
    qt_app.processEvents()

    assert widget.table.columnCount() == 9
    assert widget.table.rowCount() == 1
    assert widget.table.horizontalHeaderItem(3).text() == "Quantidade\n2023"
    assert widget.table.horizontalHeaderItem(4).text() == "Quantidade\n2024"
    assert widget.table.horizontalHeaderItem(5).text() == "Quantidade\n2025"
    assert widget.table.horizontalHeaderItem(7).text() == "Consta no PCA para 2026?"
    assert widget.table.horizontalScrollBar().maximum() >= 0
    _close(widget, qt_app)
