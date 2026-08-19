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
        "_request_automatic_detection_cancel",
        "_review_detected_candidates",
    } <= editor_methods


def test_assisted_detection_result_is_delivered_without_worker_thread_lambda() -> None:
    path = ROOT / "app/ui/template_manager/template_editor_dialog.py"
    source = path.read_text(encoding="utf-8")
    assert "worker.result_ready.connect(self._automatic_detection_ready)" in source
    assert "lambda candidates" not in source

    worker_methods = _class_method_names(
        "app/ui/template_manager/template_editor_dialog.py",
        "_AutomaticDetectionWorker",
    )
    assert {"run", "request_cancel"} <= worker_methods


def test_generated_field_shell_keeps_assisted_action_and_dropdown_responsive() -> None:
    container_source = (ROOT / "app/ui/widgets/field_container.py").read_text(encoding="utf-8")
    dropdown_source = (ROOT / "app/ui/widgets/searchable_dropdown.py").read_text(encoding="utf-8")
    form_source = (ROOT / "app/ui/widgets/document_form.py").read_text(encoding="utf-8")

    assert 'class FieldContainer(QFrame)' in container_source
    assert 'button.setText("Ajustar campo")' in container_source
    assert 'action_layout.addStretch(1)' in container_source
    assert 'QSizePolicy.Policy.Expanding' in dropdown_source
    assert 'card = FieldContainer(' in form_source
