from __future__ import annotations

"""Source-level contracts for UI constructors.

These tests deliberately avoid importing PySide6.  The real widget matrix runs
on Windows with Qt installed, while this lightweight check still catches a
common refactor regression (adding a required constructor parameter) in any
Python-only environment.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _required_init_parameters(relative_path: str, class_name: str) -> list[str]:
    path = ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    init = next(
        node
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "__init__"
    )

    positional = [*init.args.posonlyargs, *init.args.args]
    if positional and positional[0].arg == "self":
        positional = positional[1:]
    required_positional_count = max(0, len(positional) - len(init.args.defaults))
    required = [arg.arg for arg in positional[:required_positional_count]]

    for arg, default in zip(init.args.kwonlyargs, init.args.kw_defaults):
        if default is None:
            required.append(arg.arg)
    return required


def test_ui_constructor_contracts_used_by_smoke_matrix() -> None:
    contracts = {
        ("app/ui/main_window.py", "MainWindow"): [
            "project_root",
            "theme_manager",
        ],
        (
            "app/ui/dialogs/automatic_detection_dialog.py",
            "AutomaticDetectionDialog",
        ): ["candidates"],
        ("app/ui/dialogs/backup_contents_dialog.py", "BackupContentsDialog"): ["info"],
        ("app/ui/dialogs/diagnostics_dialog.py", "DiagnosticsDialog"): [
            "title",
            "report_text",
        ],
        ("app/ui/dialogs/field_library_dialog.py", "FieldLibraryDialog"): ["store"],
        ("app/ui/dialogs/filename_builder_dialog.py", "FilenameBuilderDialog"): ["pattern"],
        ("app/ui/dialogs/global_search_dialog.py", "GlobalSearchDialog"): ["records"],
        ("app/ui/dialogs/profile_manager_dialog.py", "ProfileManagerDialog"): ["store"],
        ("app/ui/dialogs/version_history_dialog.py", "VersionHistoryDialog"): [
            "repository",
            "template_id",
        ],
        (
            "app/ui/template_manager/template_manager_dialog.py",
            "TemplateManagerDialog",
        ): ["templates_dir"],
        (
            "app/ui/template_manager/template_editor_dialog.py",
            "TemplateEditorDialog",
        ): ["repository"],
        ("app/ui/widgets/document_form.py", "DocumentForm"): [],
        ("app/ui/widgets/field_layout_editor.py", "FieldLayoutEditor"): [],
        ("app/ui/widgets/file_converter_page.py", "FileConverterPage"): [],
        ("app/ui/widgets/home_page.py", "HomePage"): [],
        ("app/ui/widgets/searchable_dropdown.py", "SearchableDropdown"): [],
        ("app/ui/widgets/sidebar.py", "Sidebar"): [],
        ("app/ui/widgets/template_header.py", "TemplateHeader"): [],
        ("app/ui/widgets/tutorial_page.py", "TutorialPage"): [],
    }

    for (path, class_name), expected in contracts.items():
        assert _required_init_parameters(path, class_name) == expected, (
            f"{class_name} changed its required constructor contract. "
            "Update the caller and the real UI smoke matrix together."
        )


def _class_method_names(relative_path: str, class_name: str) -> set[str]:
    path = ROOT / relative_path
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_user_facing_review_and_template_editor_capabilities_remain_available() -> None:
    detection_methods = _class_method_names(
        "app/ui/dialogs/automatic_detection_dialog.py",
        "AutomaticDetectionDialog",
    )
    assert {
        "_apply_filters",
        "_update_details",
        "_select_visible",
    } <= detection_methods

    editor_methods = _class_method_names(
        "app/ui/template_manager/template_editor_dialog.py",
        "TemplateEditorDialog",
    )
    assert {
        "_apply_field_filters",
        "_refresh_field_validation",
        "_generate_test_document",
        "_request_field_localization_cancel",
        "_review_detected_candidates",
    } <= editor_methods


def test_field_localization_result_is_delivered_without_worker_thread_lambda() -> None:
    path = ROOT / "app/ui/template_manager/template_editor_dialog.py"
    source = path.read_text(encoding="utf-8")
    assert "worker.result_ready.connect(self._field_localization_ready)" in source
    assert "lambda candidates" not in source

    worker_methods = _class_method_names(
        "app/ui/template_manager/template_editor_dialog.py",
        "_FieldLocalizationWorker",
    )
    assert {"run", "request_cancel"} <= worker_methods


def test_template_editor_exposes_one_normal_field_localization_action() -> None:
    path = ROOT / "app/ui/template_manager/template_editor_dialog.py"
    source = path.read_text(encoding="utf-8")

    assert "self.locate_fields_button = QPushButton('Localizar campos')" in source
    assert "self.locate_fields_button.clicked.connect(self._scan_fields)" in source
    assert "self.diagnostics_button = QPushButton('Diagnóstico')" in source
    assert "Detectar campos sem tags" not in source
    assert "Ferramentas do arquivo" not in source
    assert "locate_template_fields" in source


def test_generated_field_shell_keeps_assisted_action_and_dropdown_responsive() -> None:
    container_source = (ROOT / "app/ui/widgets/field_container.py").read_text(encoding="utf-8")
    dropdown_source = (ROOT / "app/ui/widgets/searchable_dropdown.py").read_text(encoding="utf-8")
    form_source = (ROOT / "app/ui/widgets/document_form.py").read_text(encoding="utf-8")

    assert 'class FieldContainer(QFrame)' in container_source
    assert 'button.setText("Ajustar campo")' in container_source
    assert 'action_layout.addStretch(1)' in container_source
    assert 'QSizePolicy.Policy.Expanding' in dropdown_source
    assert 'card = FieldContainer(' in form_source


def test_template_authoring_uses_one_guided_four_step_flow_for_create_and_edit() -> None:
    editor_source = (
        ROOT / "app/ui/template_manager/template_editor_dialog.py"
    ).read_text(encoding="utf-8")
    stepper_source = (
        ROOT / "app/ui/widgets/creation_stepper.py"
    ).read_text(encoding="utf-8")

    assert 'self._creation_flow = True' in editor_source
    assert 'self._editing_existing = template_id is not None' in editor_source
    assert "'Escolha o documento'" in editor_source
    assert "'Confira os campos'" in editor_source
    assert "'Organize o formulário'" in editor_source
    assert "'Revise e crie'" in editor_source
    assert "'Revise e salve'" in editor_source
    assert "'Salvar alterações' if self._editing_existing else 'Criar modelo'" in editor_source
    assert "'Analisar documento →'" in editor_source
    assert 'self.fields_tabs.tabBar().hide()' in editor_source
    assert "'Opções avançadas'" in editor_source

    assert '("Documento", "Escolher arquivo")' in stepper_source
    assert '("Campos", "Conferir o que muda")' in stepper_source
    assert '("Organizar", "Ajustar o formulário")' in stepper_source
    assert '("Concluir", "Revisar e salvar")' in stepper_source




def test_guided_authoring_exposes_optional_official_letterhead() -> None:
    editor_source = (
        ROOT / "app/ui/template_manager/template_editor_dialog.py"
    ).read_text(encoding="utf-8")
    generation_source = (ROOT / "app/services/generation.py").read_text(encoding="utf-8")

    assert "Aplicar o papel timbrado oficial aos documentos gerados" in editor_source
    assert "self.letterhead_group.show()" in editor_source
    assert '"enabled": self.letterhead_checkbox.isChecked()' in editor_source
    assert "apply_letterhead(package" not in generation_source
    assert "self._apply_letterhead_if_enabled(package, staged)" in generation_source
    assert "self._apply_letterhead_if_enabled(package, temporary_docx)" in generation_source


def test_guided_creation_does_not_expose_global_widget_background_as_row_bars() -> None:
    editor_source = (
        ROOT / "app/ui/template_manager/template_editor_dialog.py"
    ).read_text(encoding="utf-8")
    light_style = (ROOT / "app/ui/styles/light.qss").read_text(encoding="utf-8")
    dark_style = (ROOT / "app/ui/styles/dark.qss").read_text(encoding="utf-8")

    assert "templateCreationFieldWrapper" in editor_source
    assert "self.top_widget.setMinimumHeight(0)" in editor_source
    assert "QWidget#templateCreationFieldWrapper" in light_style
    assert "QWidget#templateCreationFieldWrapper" in dark_style
    assert "QGroupBox#templateCreationGeneralGroup" in light_style
    assert "QGroupBox#templateCreationGeneralGroup" in dark_style
    # The guided form must not absorb spare viewport height into individual
    # rows. These policies keep the document/name wrappers at their natural
    # height and anchor the page content to the top.
    assert "QSizePolicy.Policy.Maximum" in editor_source
    assert "QSizePolicy.Policy.Fixed" in editor_source
    assert "form.setFormAlignment(" in editor_source
    assert "content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)" in editor_source


def test_creation_flow_does_not_scan_just_because_a_file_was_selected() -> None:
    source = (
        ROOT / "app/ui/template_manager/template_editor_dialog.py"
    ).read_text(encoding="utf-8")

    assert 'if self._creation_flow:' in source
    assert 'self._creation_has_scanned = False' in source
    assert 'self._creation_pending_advance = True' in source
    assert 'self._start_field_localization()' in source
    assert 'self.creation_next_button.setText(\'Analisando…\')' in source


def test_field_review_defaults_to_user_language_and_hides_technical_columns() -> None:
    source = (
        ROOT / "app/ui/dialogs/automatic_detection_dialog.py"
    ).read_text(encoding="utf-8")

    assert '"Confira o que o Padroniza encontrou"' in source
    assert '"✓ Identificado"' in source
    assert '"⚠ Confira"' in source
    assert '"? Possível campo"' in source
    assert 'self.table.setColumnHidden(2, True)' in source
    assert 'self.table.setColumnHidden(3, True)' in source
    assert '"Detalhes técnicos"' in source


def test_models_page_embeds_full_library_manager() -> None:
    """Model management belongs to the main Modelos page, not a second browser window."""

    main_source = (ROOT / "app/ui/main_window.py").read_text(encoding="utf-8")
    manager_source = (
        ROOT / "app/ui/template_manager/template_manager_dialog.py"
    ).read_text(encoding="utf-8")
    mixin_source = (ROOT / "app/ui/mixins/templates.py").read_text(encoding="utf-8")

    assert "self.template_manager_panel = TemplateManagerDialog(" in main_source
    assert "embedded=True" in main_source
    assert "template_use_requested.connect" in main_source
    assert "library_changed.connect" in main_source
    assert "self._navigate_to_target(\"templates\")" in mixin_source
    assert "if self.embedded:" in manager_source
    assert "'Usar no Gerar'" in manager_source


def test_form_grid_row_separated_exclusive_choices_share_one_qt_button_group() -> None:
    source = Path("app/ui/widgets/document_form.py").read_text(encoding="utf-8")
    assert "self.form_grid_button_groups: dict[str, QButtonGroup]" in source
    assert "self._register_form_grid_exclusive_checkbox(field, widget)" in source
    assert "button_group.addButton(widget)" in source


def test_template_test_generation_uses_interactive_preview_values() -> None:
    """Generating a test DOCX must honor selections made in the form preview."""

    source = (ROOT / "app/ui/template_manager/template_editor_dialog.py").read_text(
        encoding="utf-8"
    )
    start = source.index("    def _generate_test_document(self) -> None:")
    end = source.index("    def _selected_field_rows", start)
    method_source = source[start:end]

    assert "self.form_preview.collect_values()" in method_source
    assert "sample_values_for_fields" not in method_source
    assert "generate_docx(self.selected_docx, staged, preview_values)" in method_source
